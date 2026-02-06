"""
Security Module for ACE-Step V1.5
Provides authentication, rate limiting, and access control

Features:
- Gradio UI authentication (username/password)
- API key validation
- Rate limiting per IP/user
- IP whitelist/blacklist
- Session management
- Security logging
"""

import os
import time
import hashlib
import secrets
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Set, Callable
from functools import wraps
from loguru import logger


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class SecurityConfig:
    """Security configuration loaded from environment"""
    
    # Authentication
    auth_enabled: bool = True
    auth_username: str = "admin"
    auth_password: str = "music2026"
    
    # API Key
    api_key: Optional[str] = None
    
    # Rate Limiting
    rate_limit_per_minute: int = 30
    generation_limit_per_hour: int = 20
    
    # Access Control
    localhost_only: bool = False
    allowed_ips: Set[str] = field(default_factory=set)
    blocked_ips: Set[str] = field(default_factory=set)
    
    # Session
    session_timeout_minutes: int = 60
    
    # Logging
    log_access: bool = True
    log_auth_failures: bool = True
    
    @classmethod
    def from_env(cls) -> 'SecurityConfig':
        """Load configuration from environment variables"""
        
        def str_to_bool(s: str, default: bool = False) -> bool:
            if not s:
                return default
            return s.lower() in ('true', '1', 'yes', 'on')
        
        def str_to_set(s: str) -> Set[str]:
            if not s:
                return set()
            return {ip.strip() for ip in s.split(',') if ip.strip()}
        
        return cls(
            auth_enabled=str_to_bool(os.environ.get('ACESTEP_AUTH_ENABLED', 'true'), True),
            auth_username=os.environ.get('ACESTEP_AUTH_USERNAME', 'admin'),
            auth_password=os.environ.get('ACESTEP_AUTH_PASSWORD', 'music2026'),
            api_key=os.environ.get('ACESTEP_API_KEY'),
            rate_limit_per_minute=int(os.environ.get('ACESTEP_RATE_LIMIT_PER_MINUTE', '30')),
            generation_limit_per_hour=int(os.environ.get('ACESTEP_GENERATION_LIMIT_PER_HOUR', '20')),
            localhost_only=str_to_bool(os.environ.get('ACESTEP_LOCALHOST_ONLY', 'false')),
            allowed_ips=str_to_set(os.environ.get('ACESTEP_ALLOWED_IPS', '')),
            blocked_ips=str_to_set(os.environ.get('ACESTEP_BLOCKED_IPS', '')),
            session_timeout_minutes=int(os.environ.get('ACESTEP_SESSION_TIMEOUT_MINUTES', '60')),
            log_access=str_to_bool(os.environ.get('ACESTEP_LOG_ACCESS', 'true'), True),
            log_auth_failures=str_to_bool(os.environ.get('ACESTEP_LOG_AUTH_FAILURES', 'true'), True),
        )


# =============================================================================
# Rate Limiter
# =============================================================================

class RateLimiter:
    """
    Token bucket rate limiter with per-IP tracking
    """
    
    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()
    
    def is_allowed(self, identifier: str) -> Tuple[bool, int]:
        """
        Check if request is allowed
        
        Returns:
            (is_allowed, remaining_requests)
        """
        now = time.time()
        window_start = now - self.window_seconds
        
        with self._lock:
            # Clean old requests
            self._requests[identifier] = [
                t for t in self._requests[identifier] 
                if t > window_start
            ]
            
            current_count = len(self._requests[identifier])
            remaining = self.max_requests - current_count
            
            if current_count >= self.max_requests:
                return False, 0
            
            # Record new request
            self._requests[identifier].append(now)
            return True, remaining - 1
    
    def get_reset_time(self, identifier: str) -> float:
        """Get seconds until rate limit resets"""
        with self._lock:
            if identifier not in self._requests or not self._requests[identifier]:
                return 0
            oldest = min(self._requests[identifier])
            reset_at = oldest + self.window_seconds
            return max(0, reset_at - time.time())
    
    def cleanup(self):
        """Remove expired entries"""
        now = time.time()
        window_start = now - self.window_seconds
        
        with self._lock:
            expired = [
                k for k, v in self._requests.items() 
                if not v or max(v) < window_start
            ]
            for k in expired:
                del self._requests[k]


class GenerationLimiter:
    """
    Limits music generations per user/IP per hour
    """
    
    def __init__(self, max_generations: int = 20, window_hours: int = 1):
        self.max_generations = max_generations
        self.window_seconds = window_hours * 3600
        self._generations: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()
    
    def can_generate(self, identifier: str) -> Tuple[bool, int, str]:
        """
        Check if user can generate more music
        
        Returns:
            (can_generate, remaining, message)
        """
        now = time.time()
        window_start = now - self.window_seconds
        
        with self._lock:
            # Clean old generations
            self._generations[identifier] = [
                t for t in self._generations[identifier] 
                if t > window_start
            ]
            
            current_count = len(self._generations[identifier])
            remaining = self.max_generations - current_count
            
            if current_count >= self.max_generations:
                reset_seconds = self._generations[identifier][0] + self.window_seconds - now
                reset_minutes = int(reset_seconds / 60) + 1
                message = f"Limite de geração atingido ({self.max_generations}/hora). Tente novamente em {reset_minutes} minutos."
                return False, 0, message
            
            return True, remaining, ""
    
    def record_generation(self, identifier: str):
        """Record a generation"""
        with self._lock:
            self._generations[identifier].append(time.time())


# =============================================================================
# Session Manager
# =============================================================================

@dataclass
class Session:
    """User session data"""
    session_id: str
    username: str
    ip_address: str
    created_at: float
    last_activity: float
    generation_count: int = 0


class SessionManager:
    """
    Manages user sessions with timeout
    """
    
    def __init__(self, timeout_minutes: int = 60):
        self.timeout_seconds = timeout_minutes * 60
        self._sessions: Dict[str, Session] = {}
        self._lock = threading.Lock()
    
    def create_session(self, username: str, ip_address: str) -> str:
        """Create new session and return session ID"""
        session_id = secrets.token_urlsafe(32)
        now = time.time()
        
        session = Session(
            session_id=session_id,
            username=username,
            ip_address=ip_address,
            created_at=now,
            last_activity=now,
        )
        
        with self._lock:
            self._sessions[session_id] = session
        
        logger.info(f"Session created for {username} from {ip_address}")
        return session_id
    
    def validate_session(self, session_id: str) -> Optional[Session]:
        """Validate session and update last activity"""
        if not session_id:
            return None
        
        now = time.time()
        
        with self._lock:
            session = self._sessions.get(session_id)
            
            if not session:
                return None
            
            # Check timeout
            if self.timeout_seconds > 0:
                if now - session.last_activity > self.timeout_seconds:
                    del self._sessions[session_id]
                    logger.info(f"Session expired for {session.username}")
                    return None
            
            # Update activity
            session.last_activity = now
            return session
    
    def end_session(self, session_id: str):
        """End a session (logout)"""
        with self._lock:
            if session_id in self._sessions:
                session = self._sessions.pop(session_id)
                logger.info(f"Session ended for {session.username}")
    
    def cleanup_expired(self):
        """Remove all expired sessions"""
        if self.timeout_seconds <= 0:
            return
        
        now = time.time()
        
        with self._lock:
            expired = [
                sid for sid, s in self._sessions.items()
                if now - s.last_activity > self.timeout_seconds
            ]
            for sid in expired:
                session = self._sessions.pop(sid)
                logger.debug(f"Cleaned expired session for {session.username}")


# =============================================================================
# Security Manager (Main Class)
# =============================================================================

class SecurityManager:
    """
    Main security manager - singleton pattern
    
    Provides:
    - Authentication verification
    - Rate limiting
    - IP access control
    - Session management
    - Security logging
    """
    
    _instance: Optional['SecurityManager'] = None
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
        
        self.config = SecurityConfig.from_env()
        
        # Initialize components
        self.rate_limiter = RateLimiter(
            max_requests=self.config.rate_limit_per_minute,
            window_seconds=60
        )
        
        self.generation_limiter = GenerationLimiter(
            max_generations=self.config.generation_limit_per_hour,
            window_hours=1
        )
        
        self.session_manager = SessionManager(
            timeout_minutes=self.config.session_timeout_minutes
        )
        
        # Failed login tracking (for lockout)
        self._failed_logins: Dict[str, List[float]] = defaultdict(list)
        self._failed_login_lock = threading.Lock()
        
        self._initialized = True
        
        logger.info(f"SecurityManager initialized (auth_enabled={self.config.auth_enabled})")
    
    def get_gradio_auth(self) -> Optional[Tuple[str, str]]:
        """
        Get authentication tuple for Gradio
        
        Returns:
            (username, password) tuple or None if auth disabled
        """
        if not self.config.auth_enabled:
            return None
        
        return (self.config.auth_username, self.config.auth_password)
    
    def verify_gradio_auth(self, username: str, password: str) -> bool:
        """
        Verify Gradio login credentials
        
        Returns:
            True if valid, False otherwise
        """
        if not self.config.auth_enabled:
            return True
        
        valid = (
            username == self.config.auth_username and 
            password == self.config.auth_password
        )
        
        if not valid and self.config.log_auth_failures:
            logger.warning(f"Failed login attempt for username: {username}")
        
        return valid
    
    def verify_api_key(self, provided_key: Optional[str]) -> bool:
        """
        Verify API key
        
        Returns:
            True if valid or no key required, False otherwise
        """
        if not self.config.api_key:
            return True  # No API key configured
        
        if not provided_key:
            return False
        
        # Remove "Bearer " prefix if present
        if provided_key.startswith("Bearer "):
            provided_key = provided_key[7:]
        
        valid = secrets.compare_digest(provided_key, self.config.api_key)
        
        if not valid and self.config.log_auth_failures:
            logger.warning(f"Invalid API key attempt: {provided_key[:8]}...")
        
        return valid
    
    def check_ip_access(self, ip_address: str) -> Tuple[bool, str]:
        """
        Check if IP is allowed to access
        
        Returns:
            (is_allowed, message)
        """
        # Normalize IP
        ip = ip_address.strip()
        
        # Check blocked list
        if ip in self.config.blocked_ips:
            if self.config.log_access:
                logger.warning(f"Blocked IP attempted access: {ip}")
            return False, "Acesso bloqueado"
        
        # Check localhost only
        if self.config.localhost_only:
            if ip not in ('127.0.0.1', 'localhost', '::1'):
                return False, "Apenas acesso local permitido"
        
        # Check allowed list (if configured)
        if self.config.allowed_ips:
            if ip not in self.config.allowed_ips:
                return False, "IP não autorizado"
        
        return True, ""
    
    def check_rate_limit(self, ip_address: str) -> Tuple[bool, int, str]:
        """
        Check rate limit for IP
        
        Returns:
            (is_allowed, remaining, message)
        """
        allowed, remaining = self.rate_limiter.is_allowed(ip_address)
        
        if not allowed:
            reset_time = self.rate_limiter.get_reset_time(ip_address)
            message = f"Rate limit excedido. Tente novamente em {int(reset_time)} segundos."
            
            if self.config.log_access:
                logger.warning(f"Rate limit exceeded for IP: {ip_address}")
            
            return False, 0, message
        
        return True, remaining, ""
    
    def check_generation_limit(self, identifier: str) -> Tuple[bool, int, str]:
        """
        Check generation limit for user/IP
        
        Returns:
            (can_generate, remaining, message)
        """
        return self.generation_limiter.can_generate(identifier)
    
    def record_generation(self, identifier: str):
        """Record a successful generation"""
        self.generation_limiter.record_generation(identifier)
    
    def log_access(self, ip_address: str, endpoint: str, username: Optional[str] = None):
        """Log access attempt"""
        if self.config.log_access:
            user_info = f" (user: {username})" if username else ""
            logger.debug(f"Access: {ip_address} -> {endpoint}{user_info}")
    
    def get_security_headers(self) -> Dict[str, str]:
        """Get security headers for HTTP responses"""
        return {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Cache-Control": "no-store, no-cache, must-revalidate",
        }
    
    def get_status(self) -> Dict[str, any]:
        """Get security status for monitoring"""
        return {
            "auth_enabled": self.config.auth_enabled,
            "api_key_configured": bool(self.config.api_key),
            "rate_limit_per_minute": self.config.rate_limit_per_minute,
            "generation_limit_per_hour": self.config.generation_limit_per_hour,
            "localhost_only": self.config.localhost_only,
            "allowed_ips_count": len(self.config.allowed_ips),
            "blocked_ips_count": len(self.config.blocked_ips),
            "session_timeout_minutes": self.config.session_timeout_minutes,
        }


# =============================================================================
# Decorator for securing functions
# =============================================================================

def require_auth(func: Callable) -> Callable:
    """
    Decorator to require authentication
    
    Usage:
        @require_auth
        def my_secure_function(request, ...):
            ...
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        manager = get_security_manager()
        
        # Try to get request from args/kwargs
        request = kwargs.get('request') or (args[0] if args else None)
        
        if request:
            # Check API key from header
            auth_header = getattr(request, 'headers', {}).get('Authorization')
            if not manager.verify_api_key(auth_header):
                raise PermissionError("Invalid or missing API key")
            
            # Check IP
            client_ip = getattr(request, 'client', {})
            if hasattr(client_ip, 'host'):
                allowed, msg = manager.check_ip_access(client_ip.host)
                if not allowed:
                    raise PermissionError(msg)
        
        return func(*args, **kwargs)
    
    return wrapper


def rate_limited(func: Callable) -> Callable:
    """
    Decorator to apply rate limiting
    
    Usage:
        @rate_limited
        def my_api_endpoint(request, ...):
            ...
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        manager = get_security_manager()
        
        # Try to get client IP
        request = kwargs.get('request') or (args[0] if args else None)
        client_ip = "unknown"
        
        if request:
            client = getattr(request, 'client', None)
            if client and hasattr(client, 'host'):
                client_ip = client.host
        
        allowed, remaining, msg = manager.check_rate_limit(client_ip)
        if not allowed:
            raise Exception(msg)
        
        return func(*args, **kwargs)
    
    return wrapper


# =============================================================================
# Helper Functions
# =============================================================================

def get_security_manager() -> SecurityManager:
    """Get the singleton SecurityManager instance"""
    return SecurityManager()


def generate_api_key() -> str:
    """Generate a secure API key"""
    return f"sk-acestep-{secrets.token_urlsafe(32)}"


def hash_password(password: str) -> str:
    """Hash a password using SHA-256 with salt"""
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{hashed}"


def verify_password_hash(password: str, hashed: str) -> bool:
    """Verify a password against its hash"""
    try:
        salt, expected_hash = hashed.split(':')
        actual_hash = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
        return secrets.compare_digest(actual_hash, expected_hash)
    except Exception:
        return False


# =============================================================================
# Initialize on import
# =============================================================================

def init_security():
    """Initialize security system"""
    manager = get_security_manager()
    status = manager.get_status()
    
    logger.info("="*60)
    logger.info("🔒 Security System Initialized")
    logger.info("="*60)
    logger.info(f"  Authentication: {'Enabled' if status['auth_enabled'] else 'Disabled'}")
    logger.info(f"  API Key: {'Configured' if status['api_key_configured'] else 'Not Set'}")
    logger.info(f"  Rate Limit: {status['rate_limit_per_minute']}/min")
    logger.info(f"  Generation Limit: {status['generation_limit_per_hour']}/hour")
    
    if status['localhost_only']:
        logger.info(f"  Access: Localhost Only")
    elif status['allowed_ips_count'] > 0:
        logger.info(f"  Access: {status['allowed_ips_count']} IPs whitelisted")
    else:
        logger.info(f"  Access: All IPs allowed")
    
    logger.info("="*60)
    
    return manager


# Auto-initialize if environment indicates
if os.environ.get('ACESTEP_AUTH_ENABLED', 'true').lower() in ('true', '1', 'yes'):
    try:
        init_security()
    except Exception as e:
        logger.warning(f"Failed to auto-initialize security: {e}")
