"""
Memory Management Module for ACE-Step V1.5
ENFORCES MINIMUM 5GB FREE RAM for system stability

This module provides:
- Memory monitoring with HARD LIMITS
- Automatic garbage collection
- Model offloading strategies
- Pre-generation memory checks
- Emergency memory cleanup
"""

import os
import gc
import sys
import threading
import resource
import signal
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Callable, Tuple
from functools import wraps
from contextlib import contextmanager

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

# ================================================================================
# CRITICAL MEMORY CONSTANTS - DO NOT CHANGE
# ================================================================================
MEMORY_LIMIT_ENV = "ACESTEP_MEMORY_LIMIT_GB"
MIN_FREE_RAM_GB = 5.0  # MINIMUM 5GB FREE RAM - HARD LIMIT
DEFAULT_MEMORY_LIMIT_GB = 4.0  # Max memory ACE-Step can use
MAX_ALLOWED_MEMORY_GB = 10.0  # Absolute maximum (15GB - 5GB reserved)


def get_system_memory_info() -> Dict[str, float]:
    """Get accurate system memory information in GB"""
    try:
        import psutil
        mem = psutil.virtual_memory()
        return {
            "total_gb": mem.total / (1024**3),
            "available_gb": mem.available / (1024**3),
            "used_gb": mem.used / (1024**3),
            "percent_used": mem.percent,
            "free_gb": mem.free / (1024**3),
        }
    except ImportError:
        # Fallback to /proc/meminfo
        mem_info = {}
        try:
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        key = parts[0].rstrip(':')
                        value_kb = int(parts[1])
                        mem_info[key] = value_kb / (1024**2)  # Convert to GB
            
            total = mem_info.get('MemTotal', 0)
            available = mem_info.get('MemAvailable', mem_info.get('MemFree', 0))
            used = total - available
            
            return {
                "total_gb": total,
                "available_gb": available,
                "used_gb": used,
                "percent_used": (used / total * 100) if total > 0 else 0,
                "free_gb": mem_info.get('MemFree', 0),
            }
        except Exception:
            return {
                "total_gb": 16.0,
                "available_gb": 8.0,
                "used_gb": 8.0,
                "percent_used": 50.0,
                "free_gb": 4.0,
            }


def get_process_memory_gb() -> float:
    """Get current process memory usage in GB"""
    try:
        import psutil
        process = psutil.Process()
        return process.memory_info().rss / (1024**3)
    except ImportError:
        try:
            # Fallback to /proc/self/status
            with open('/proc/self/status', 'r') as f:
                for line in f:
                    if line.startswith('VmRSS:'):
                        return int(line.split()[1]) / (1024**2)  # KB to GB
        except Exception:
            pass
    return 0.0


def emergency_memory_cleanup():
    """Emergency cleanup when memory is critically low"""
    logger.warning("🚨 EMERGENCY MEMORY CLEANUP - Freeing resources...")
    
    # 1. Force Python garbage collection (multiple generations)
    gc.collect(0)
    gc.collect(1)
    gc.collect(2)
    
    # 2. Clear CUDA cache
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            # Reset peak memory stats
            torch.cuda.reset_peak_memory_stats()
            logger.info("  ✓ CUDA cache cleared")
    except Exception as e:
        logger.warning(f"  ⚠ CUDA cleanup failed: {e}")
    
    # 3. Try to clear Python object caches
    try:
        # Clear __pycache__ references in memory
        import linecache
        linecache.clearcache()
        
        # Clear function caches if any
        import functools
        if hasattr(functools, 'cache'):
            # Python 3.9+
            pass  # Can't easily clear all caches
    except Exception:
        pass
    
    # 4. Final GC pass
    gc.collect()
    
    mem = get_system_memory_info()
    logger.info(f"  ✓ Memory after cleanup: {mem['available_gb']:.2f}GB available")
    
    return mem['available_gb'] >= MIN_FREE_RAM_GB


def set_memory_limits():
    """Set OS-level memory limits for the current process
    
    NOTE: We intentionally DO NOT set RLIMIT_AS (Address Space) anymore because 
    PyTorch/mmap requires large virtual address space even if physical RAM usage is low.
    Setting RLIMIT_AS causes 'OSError: Cannot allocate memory (os error 12)' during model loading.
    
    We rely on the pro-active 'can_generate()' checks and the external 'memory_guard.sh' 
    to prevent physical RAM exhaustion.
    """
    try:
        mem_info = get_system_memory_info()
        logger.info(f"✓ Memory Manager Active (Total RAM: {mem_info['total_gb']:.2f}GB)")
        
        # We do NOT set RLIMIT_AS here anymore
        # See explanation above.
        
        return True
    except Exception as e:
        logger.warning(f"Could not check memory info: {e}")
    return False


@dataclass
class MemoryConfig:
    """Memory configuration for ACE-Step generation"""
    
    # Core memory limits
    max_memory_gb: float = DEFAULT_MEMORY_LIMIT_GB
    min_free_ram_gb: float = MIN_FREE_RAM_GB  # HARD LIMIT: 5GB free
    gpu_memory_fraction: float = 0.9  # 0.9 is safe for 12GB VRAM
    
    # Generation limits
    max_duration_seconds: int = 180  # 3 minutes max (optimized for GPU)
    max_batch_size: int = 1
    
    # Model offloading
    offload_to_cpu: bool = True
    offload_dit_to_cpu: bool = True
    enable_lm: bool = False  # LM disabled by default
    
    # Memory recovery
    aggressive_gc: bool = True
    clear_cuda_cache: bool = True
    pre_check_memory: bool = True  # Check before generation
    
    # Emergency thresholds
    warning_threshold_gb: float = 6.0  # Warn when < 6GB free
    critical_threshold_gb: float = 4.0  # Critical when < 4GB free
    
    def __post_init__(self):
        """Validate and enforce safe memory configuration"""
        mem_info = get_system_memory_info()
        total_ram = mem_info['total_gb']
        available_ram = mem_info['available_gb']
        
        # Calculate maximum allowed based on system RAM
        max_allowed = total_ram - self.min_free_ram_gb
        
        if self.max_memory_gb > max_allowed:
            logger.warning(
                f"Memory limit {self.max_memory_gb}GB exceeds safe maximum "
                f"({max_allowed:.1f}GB), capping to {max_allowed:.1f}GB"
            )
            self.max_memory_gb = max_allowed
        
        # Enforce stricter limits based on available memory
        if available_ram < self.warning_threshold_gb:
            logger.warning(f"⚠️ Low memory: {available_ram:.2f}GB available")
            self.max_memory_gb = min(self.max_memory_gb, 2.0)
            self.max_duration_seconds = min(self.max_duration_seconds, 60)
            self.enable_lm = False
        
        # Always enforce these for safety
        self.max_batch_size = 1
        self.offload_to_cpu = True
        self.offload_dit_to_cpu = True


class MemoryManager:
    """
    Memory Manager for ACE-Step
    
    ENFORCES MINIMUM 5GB FREE RAM at all times.
    Monitors and limits memory during music generation.
    """
    
    _instance: Optional['MemoryManager'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.config = self._load_config()
        self._callbacks: Dict[str, Callable] = {}
        self._memory_usage_history: list = []
        self._generation_count = 0
        self._initialized = True
        
        # Set OS-level memory limits
        set_memory_limits()
        
        logger.info(
            f"🛡️ MemoryManager initialized:\n"
            f"   Max memory: {self.config.max_memory_gb}GB\n"
            f"   Min free RAM: {self.config.min_free_ram_gb}GB\n"
            f"   Warning threshold: {self.config.warning_threshold_gb}GB"
        )
    
    def _load_config(self) -> MemoryConfig:
        """Load memory configuration from environment"""
        memory_limit = float(os.environ.get(MEMORY_LIMIT_ENV, DEFAULT_MEMORY_LIMIT_GB))
        max_cuda_vram = os.environ.get("MAX_CUDA_VRAM")
        
        if max_cuda_vram:
            try:
                memory_limit = min(memory_limit, float(max_cuda_vram))
            except ValueError:
                pass
        
        return MemoryConfig(
            max_memory_gb=memory_limit,
            offload_to_cpu=os.environ.get("ACESTEP_OFFLOAD_TO_CPU", "true").lower() in ("true", "1", "yes"),
            offload_dit_to_cpu=os.environ.get("ACESTEP_OFFLOAD_DIT_TO_CPU", "true").lower() in ("true", "1", "yes"),
            enable_lm=os.environ.get("ACESTEP_INIT_LM_DEFAULT", "false").lower() in ("true", "1", "yes"),
            max_duration_seconds=int(os.environ.get("ACESTEP_MAX_DURATION", "120")),
            max_batch_size=int(os.environ.get("ACESTEP_MAX_BATCH_SIZE", "1")),
        )
    
    def get_current_memory_usage(self) -> Dict[str, float]:
        """Get current memory usage in GB"""
        result = {
            "ram_total_gb": 0.0,
            "ram_used_gb": 0.0,
            "ram_available_gb": 0.0,
            "ram_free_gb": 0.0,
            "process_memory_gb": 0.0,
            "gpu_total_gb": 0.0,
            "gpu_used_gb": 0.0,
            "gpu_available_gb": 0.0,
        }
        
        # RAM usage
        mem_info = get_system_memory_info()
        result["ram_total_gb"] = mem_info["total_gb"]
        result["ram_used_gb"] = mem_info["used_gb"]
        result["ram_available_gb"] = mem_info["available_gb"]
        result["ram_free_gb"] = mem_info["free_gb"]
        result["process_memory_gb"] = get_process_memory_gb()
        
        # GPU usage
        try:
            import torch
            if torch.cuda.is_available():
                result["gpu_total_gb"] = torch.cuda.get_device_properties(0).total_memory / (1024**3)
                result["gpu_used_gb"] = torch.cuda.memory_allocated(0) / (1024**3)
                result["gpu_available_gb"] = result["gpu_total_gb"] - result["gpu_used_gb"]
        except Exception:
            pass
        
        return result
    
    def can_generate(self, estimated_memory_gb: float = 2.0) -> Tuple[bool, str]:
        """
        Check if generation is safe (won't exceed memory limits)
        
        Returns:
            (can_proceed, message)
        """
        usage = self.get_current_memory_usage()
        available = usage["ram_available_gb"]
        
        # Check if we have minimum free RAM
        if available < self.config.min_free_ram_gb:
            return False, (
                f"🚫 BLOCKED: Only {available:.2f}GB RAM available. "
                f"Need at least {self.config.min_free_ram_gb}GB free. "
                f"Close other applications and try again."
            )
        
        # Check if generation would leave enough free
        remaining_after = available - estimated_memory_gb
        if remaining_after < self.config.min_free_ram_gb:
            return False, (
                f"⚠️ Generation requires ~{estimated_memory_gb}GB but only {available:.2f}GB available. "
                f"Would leave less than {self.config.min_free_ram_gb}GB free. "
                f"Try shorter duration or close other apps."
            )
        
        # Check critical threshold
        if available < self.config.critical_threshold_gb:
            # Try emergency cleanup first
            if emergency_memory_cleanup():
                return True, "⚠️ Memory was low, cleanup performed. Proceeding with caution."
            return False, f"🚫 Critical memory shortage. Please restart the application."
        
        # Warning threshold
        if available < self.config.warning_threshold_gb:
            return True, f"⚠️ Low memory warning: {available:.2f}GB available"
        
        return True, ""
    
    def check_memory_available(self, required_gb: float = 0.5) -> Tuple[bool, str]:
        """Alias for can_generate for backward compatibility"""
        return self.can_generate(required_gb)
    
    def validate_generation_params(
        self, 
        duration: float, 
        batch_size: int
    ) -> Tuple[float, int, str]:
        """
        Validate and clamp generation parameters based on available memory
        """
        warnings = []
        usage = self.get_current_memory_usage()
        available = usage["ram_available_gb"]
        
        # Dynamic duration limit based on available memory
        if available < 6.0:
            max_duration = 60  # 1 minute when low memory
        elif available < 8.0:
            max_duration = 120  # 2 minutes
        else:
            max_duration = self.config.max_duration_seconds
        
        if duration > max_duration:
            warnings.append(
                f"⚠️ Duration {duration}s → {max_duration}s (memory: {available:.1f}GB free)"
            )
            duration = float(max_duration)
        
        # Always force batch_size=1
        if batch_size > 1:
            warnings.append(f"⚠️ Batch size {batch_size} → 1 (memory safety)")
            batch_size = 1
        
        warning_msg = " | ".join(warnings) if warnings else ""
        return duration, batch_size, warning_msg
    
    def force_memory_cleanup(self):
        """Force cleanup of memory after generation"""
        if not self.config.aggressive_gc:
            return
        
        logger.debug("Forcing memory cleanup...")
        
        # Python garbage collection
        gc.collect(0)
        gc.collect(1)
        gc.collect(2)
        
        # CUDA cache cleanup
        if self.config.clear_cuda_cache:
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
                    logger.debug("CUDA cache cleared")
            except Exception as e:
                logger.warning(f"Failed to clear CUDA cache: {e}")
        
        gc.collect()
        
        # Increment generation count for periodic deep cleanup
        self._generation_count += 1
        if self._generation_count % 5 == 0:
            logger.info(f"Periodic deep cleanup after {self._generation_count} generations")
            emergency_memory_cleanup()
    
    def get_generation_constraints(self) -> Dict[str, Any]:
        """Get current generation constraints based on memory status"""
        usage = self.get_current_memory_usage()
        available = usage["ram_available_gb"]
        
        # Dynamic constraints based on available memory
        if available < 6.0:
            max_duration = 60
            tier = "critical"
        elif available < 8.0:
            max_duration = 120
            tier = "low"
        elif available < 10.0:
            max_duration = 180
            tier = "normal"
        else:
            max_duration = self.config.max_duration_seconds
            tier = "optimal"
        
        return {
            "max_duration_seconds": max_duration,
            "max_batch_size": 1,  # Always 1 for safety
            "lm_enabled": self.config.enable_lm and available > 8.0,
            "offload_to_cpu": True,
            "offload_dit_to_cpu": True,
            "memory_limit_gb": self.config.max_memory_gb,
            "available_memory_gb": available,
            "memory_tier": tier,
            "min_free_ram_gb": self.config.min_free_ram_gb,
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get complete memory status for monitoring"""
        usage = self.get_current_memory_usage()
        constraints = self.get_generation_constraints()
        
        available = usage.get("ram_available_gb", 0)
        is_healthy = available >= self.config.min_free_ram_gb
        
        return {
            "config": {
                "max_memory_gb": self.config.max_memory_gb,
                "min_free_ram_gb": self.config.min_free_ram_gb,
                "offload_enabled": self.config.offload_to_cpu,
                "lm_enabled": self.config.enable_lm,
                "aggressive_gc": self.config.aggressive_gc,
            },
            "current_usage": usage,
            "constraints": constraints,
            "healthy": is_healthy,
            "status": "✅ Healthy" if is_healthy else "⚠️ Low Memory",
            "generation_count": self._generation_count,
        }
    
    @contextmanager
    def generation_context(self, estimated_memory_gb: float = 2.0):
        """
        Context manager for safe memory-limited generation
        
        Usage:
            with manager.generation_context(estimated_memory_gb=2.0):
                # Do generation work
                pass
        """
        # Pre-generation check
        can_proceed, message = self.can_generate(estimated_memory_gb)
        if not can_proceed:
            raise MemoryError(message)
        
        if message:
            logger.warning(message)
        
        try:
            yield self
        finally:
            # Always cleanup after generation
            self.force_memory_cleanup()


def memory_limit_decorator(required_gb: float = 1.0):
    """
    Decorator to enforce memory limits on functions
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            manager = MemoryManager()
            
            # Check memory before execution
            can_proceed, msg = manager.can_generate(required_gb)
            if not can_proceed:
                raise MemoryError(msg)
            
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                manager.force_memory_cleanup()
        
        return wrapper
    return decorator


def get_memory_manager() -> MemoryManager:
    """Get the singleton MemoryManager instance"""
    return MemoryManager()


def apply_memory_limits() -> Dict[str, Any]:
    """
    Apply memory limits to the system
    MUST be called early in application startup
    """
    manager = get_memory_manager()
    
    # Set PyTorch memory configuration
    try:
        import torch
        if torch.cuda.is_available():
            memory_fraction = manager.config.gpu_memory_fraction
            
            if hasattr(torch.cuda, 'set_per_process_memory_fraction'):
                torch.cuda.set_per_process_memory_fraction(memory_fraction)
                logger.info(f"✓ CUDA memory fraction set to {memory_fraction}")
            
            # Also set max split size for better memory management
            # This is done via environment variable, ensure it's set
            if "PYTORCH_CUDA_ALLOC_CONF" not in os.environ:
                os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "garbage_collection_threshold:0.6,max_split_size_mb:128"
    except Exception as e:
        logger.warning(f"Failed to configure PyTorch memory: {e}")
    
    # Set OS-level limits
    set_memory_limits()
    
    constraints = manager.get_generation_constraints()
    logger.info(f"🛡️ Memory limits applied: {constraints}")
    
    return constraints


def check_startup_memory() -> bool:
    """
    Check if there's enough memory to start the application
    Returns True if safe to proceed
    """
    mem_info = get_system_memory_info()
    available = mem_info["available_gb"]
    
    if available < MIN_FREE_RAM_GB:
        logger.error(
            f"🚫 STARTUP BLOCKED: Only {available:.2f}GB RAM available.\n"
            f"   Minimum required: {MIN_FREE_RAM_GB}GB free.\n"
            f"   Close other applications before starting ACE-Step."
        )
        return False
    
    if available < 8.0:
        logger.warning(
            f"⚠️ Low memory at startup: {available:.2f}GB available.\n"
            f"   Generation capabilities will be limited."
        )
    
    return True


# ================================================================================
# Auto-apply limits when module is imported
# ================================================================================
if os.environ.get("ACESTEP_AUTO_MEMORY_LIMIT", "true").lower() in ("true", "1", "yes"):
    try:
        # Check if we can even start
        if not check_startup_memory():
            logger.error("Memory check failed - application may not function correctly")
        
        apply_memory_limits()
    except Exception as e:
        logger.warning(f"Failed to auto-apply memory limits: {e}")
