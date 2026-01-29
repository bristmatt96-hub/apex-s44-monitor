"""
Multi-Agent Framework Utilities
Provides thread-safe file operations, health monitoring, retry logic, and logging
"""

import json
import os
import time
import fcntl
import logging
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Callable, TypeVar
from functools import wraps
from threading import Lock, Thread, Event
from collections import defaultdict

# ============== LOGGING INFRASTRUCTURE ==============

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

def setup_logger(name: str, log_file: str = None, level: int = logging.INFO) -> logging.Logger:
    """Create a logger with file and console handlers"""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler
    if log_file is None:
        log_file = LOG_DIR / f"{name}.log"
    else:
        log_file = LOG_DIR / log_file

    file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

# Create default agent logger
agent_logger = setup_logger("agent_framework")

# ============== FILE LOCKING FOR JSON OPERATIONS ==============

class FileLock:
    """Context manager for file locking using fcntl"""

    def __init__(self, file_path: Path, timeout: float = 10.0):
        self.file_path = Path(file_path)
        self.timeout = timeout
        self.lock_file = None
        self._lock_path = self.file_path.with_suffix(self.file_path.suffix + '.lock')

    def __enter__(self):
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file = open(self._lock_path, 'w')

        start_time = time.time()
        while True:
            try:
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except (IOError, OSError):
                if time.time() - start_time > self.timeout:
                    raise TimeoutError(f"Could not acquire lock on {self.file_path} within {self.timeout}s")
                time.sleep(0.1)

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.lock_file:
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
            self.lock_file.close()
        return False


def safe_json_read(file_path: Path, default: Any = None) -> Any:
    """Thread-safe JSON file read with file locking"""
    file_path = Path(file_path)

    if not file_path.exists():
        return default if default is not None else {}

    try:
        with FileLock(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        agent_logger.error(f"Error reading {file_path}: {e}")
        return default if default is not None else {}


def safe_json_write(file_path: Path, data: Any, indent: int = 2) -> bool:
    """Thread-safe JSON file write with file locking and atomic write"""
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file first, then rename (atomic operation)
    temp_path = file_path.with_suffix(file_path.suffix + '.tmp')

    try:
        with FileLock(file_path):
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=indent, ensure_ascii=False)

            # Atomic rename
            os.replace(temp_path, file_path)
            return True
    except Exception as e:
        agent_logger.error(f"Error writing {file_path}: {e}")
        # Clean up temp file if it exists
        if temp_path.exists():
            try:
                temp_path.unlink()
            except:
                pass
        return False


def safe_json_update(file_path: Path, update_func: Callable[[Dict], Dict], default: Any = None) -> bool:
    """Thread-safe read-modify-write operation on JSON file"""
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with FileLock(file_path):
            # Read existing data
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = default if default is not None else {}

            # Apply update
            updated_data = update_func(data)

            # Write back atomically
            temp_path = file_path.with_suffix(file_path.suffix + '.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(updated_data, f, indent=2, ensure_ascii=False)

            os.replace(temp_path, file_path)
            return True
    except Exception as e:
        agent_logger.error(f"Error updating {file_path}: {e}")
        return False


# ============== RETRY LOGIC WITH EXPONENTIAL BACKOFF ==============

T = TypeVar('T')

class RetryError(Exception):
    """Raised when all retry attempts are exhausted"""
    def __init__(self, message: str, last_exception: Exception = None):
        super().__init__(message)
        self.last_exception = last_exception


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    exceptions: tuple = (Exception,),
    logger: logging.Logger = None
) -> Callable:
    """
    Decorator for retry with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay between retries (seconds)
        exponential_base: Base for exponential backoff calculation
        exceptions: Tuple of exceptions to catch and retry on
        logger: Logger instance for logging retries
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            log = logger or agent_logger
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_retries:
                        log.error(f"{func.__name__} failed after {max_retries + 1} attempts: {e}")
                        raise RetryError(
                            f"{func.__name__} failed after {max_retries + 1} attempts",
                            last_exception=e
                        )

                    delay = min(base_delay * (exponential_base ** attempt), max_delay)
                    log.warning(f"{func.__name__} attempt {attempt + 1} failed: {e}. Retrying in {delay:.1f}s...")
                    time.sleep(delay)

            raise RetryError(f"{func.__name__} failed", last_exception=last_exception)
        return wrapper
    return decorator


def call_with_retry(
    func: Callable[..., T],
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    exceptions: tuple = (Exception,),
    **kwargs
) -> T:
    """
    Call a function with retry logic.

    This is the functional alternative to the decorator, useful for
    one-off calls or when decorating isn't possible.
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except exceptions as e:
            last_exception = e

            if attempt == max_retries:
                agent_logger.error(f"Function call failed after {max_retries + 1} attempts: {e}")
                raise RetryError(
                    f"Function call failed after {max_retries + 1} attempts",
                    last_exception=e
                )

            delay = base_delay * (2 ** attempt)
            agent_logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay:.1f}s...")
            time.sleep(delay)

    raise RetryError("Function call failed", last_exception=last_exception)


# ============== THREAD HEALTH MONITORING ==============

class ThreadHealthMonitor:
    """
    Monitors background threads and provides health status and recovery.

    Features:
    - Heartbeat tracking
    - Automatic thread restart on failure
    - Health status reporting
    """

    def __init__(self, logger: logging.Logger = None):
        self.logger = logger or agent_logger
        self._threads: Dict[str, Dict] = {}
        self._lock = Lock()
        self._monitor_thread = None
        self._stop_event = Event()

    def register_thread(
        self,
        name: str,
        target: Callable,
        args: tuple = (),
        kwargs: dict = None,
        heartbeat_timeout: float = 300.0,
        auto_restart: bool = True,
        daemon: bool = True
    ) -> Thread:
        """
        Register and start a monitored thread.

        Args:
            name: Unique name for the thread
            target: The function to run in the thread
            args: Arguments to pass to target
            kwargs: Keyword arguments to pass to target
            heartbeat_timeout: Seconds before thread is considered dead
            auto_restart: Whether to automatically restart dead threads
            daemon: Whether thread should be a daemon thread
        """
        kwargs = kwargs or {}

        with self._lock:
            # Stop existing thread if any
            if name in self._threads:
                self._stop_thread(name)

            # Create wrapped target that tracks heartbeat
            heartbeat_key = f"_heartbeat_{name}"

            def monitored_target():
                try:
                    self._threads[name]['last_heartbeat'] = time.time()
                    self._threads[name]['status'] = 'running'
                    self.logger.info(f"Thread '{name}' started")

                    # Run the actual target
                    target(*args, **kwargs)

                    self._threads[name]['status'] = 'completed'
                    self.logger.info(f"Thread '{name}' completed normally")
                except Exception as e:
                    self._threads[name]['status'] = 'error'
                    self._threads[name]['last_error'] = str(e)
                    self.logger.error(f"Thread '{name}' crashed: {e}")

            # Create and start thread
            thread = Thread(target=monitored_target, name=name, daemon=daemon)

            self._threads[name] = {
                'thread': thread,
                'target': target,
                'args': args,
                'kwargs': kwargs,
                'heartbeat_timeout': heartbeat_timeout,
                'auto_restart': auto_restart,
                'daemon': daemon,
                'last_heartbeat': time.time(),
                'status': 'starting',
                'restart_count': 0,
                'last_error': None
            }

            thread.start()
            return thread

    def heartbeat(self, name: str):
        """Update heartbeat for a thread. Call this periodically from within the thread."""
        with self._lock:
            if name in self._threads:
                self._threads[name]['last_heartbeat'] = time.time()

    def get_health_status(self) -> Dict[str, Dict]:
        """Get health status of all registered threads"""
        with self._lock:
            status = {}
            for name, info in self._threads.items():
                thread = info['thread']
                last_heartbeat = info['last_heartbeat']
                timeout = info['heartbeat_timeout']

                is_alive = thread.is_alive()
                heartbeat_age = time.time() - last_heartbeat
                is_healthy = is_alive and heartbeat_age < timeout

                status[name] = {
                    'alive': is_alive,
                    'healthy': is_healthy,
                    'status': info['status'],
                    'last_heartbeat_age': heartbeat_age,
                    'restart_count': info['restart_count'],
                    'last_error': info['last_error']
                }
            return status

    def is_healthy(self, name: str) -> bool:
        """Check if a specific thread is healthy"""
        status = self.get_health_status()
        return status.get(name, {}).get('healthy', False)

    def _stop_thread(self, name: str):
        """Mark thread as stopped (daemon threads will be killed on exit)"""
        if name in self._threads:
            self._threads[name]['status'] = 'stopped'

    def restart_thread(self, name: str) -> bool:
        """Manually restart a thread"""
        with self._lock:
            if name not in self._threads:
                return False

            info = self._threads[name]
            info['restart_count'] += 1

            self.logger.info(f"Restarting thread '{name}' (restart #{info['restart_count']})")

            # Create new thread with same config
            thread = Thread(
                target=info['target'],
                args=info['args'],
                kwargs=info['kwargs'],
                name=name,
                daemon=info['daemon']
            )

            info['thread'] = thread
            info['status'] = 'restarting'
            info['last_heartbeat'] = time.time()

            thread.start()
            return True

    def start_monitor(self, check_interval: float = 60.0):
        """Start the background health monitor"""
        if self._monitor_thread is not None:
            return

        def monitor_loop():
            while not self._stop_event.is_set():
                self._check_and_restart_threads()
                self._stop_event.wait(check_interval)

        self._monitor_thread = Thread(target=monitor_loop, daemon=True, name='health_monitor')
        self._monitor_thread.start()
        self.logger.info("Health monitor started")

    def stop_monitor(self):
        """Stop the background health monitor"""
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)

    def _check_and_restart_threads(self):
        """Check thread health and restart failed threads"""
        with self._lock:
            for name, info in list(self._threads.items()):
                thread = info['thread']
                last_heartbeat = info['last_heartbeat']
                timeout = info['heartbeat_timeout']

                is_alive = thread.is_alive()
                heartbeat_age = time.time() - last_heartbeat

                # Check if thread needs restart
                needs_restart = (
                    info['auto_restart'] and
                    (not is_alive or heartbeat_age > timeout) and
                    info['status'] not in ('completed', 'stopped')
                )

                if needs_restart:
                    self.logger.warning(
                        f"Thread '{name}' unhealthy (alive={is_alive}, "
                        f"heartbeat_age={heartbeat_age:.0f}s). Restarting..."
                    )
                    self.restart_thread(name)


# Global thread monitor instance
thread_monitor = ThreadHealthMonitor()


# ============== THREAD-SAFE DATA STRUCTURES ==============

class ThreadSafeDict:
    """A thread-safe dictionary with lock-protected access"""

    def __init__(self, initial: Dict = None):
        self._data = initial or {}
        self._lock = Lock()

    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value):
        with self._lock:
            self._data[key] = value

    def delete(self, key: str):
        with self._lock:
            if key in self._data:
                del self._data[key]

    def update(self, data: Dict):
        with self._lock:
            self._data.update(data)

    def get_all(self) -> Dict:
        with self._lock:
            return dict(self._data)

    def clear(self):
        with self._lock:
            self._data.clear()

    def __contains__(self, key):
        with self._lock:
            return key in self._data

    def __len__(self):
        with self._lock:
            return len(self._data)


class ThreadSafeSet:
    """A thread-safe set with lock-protected access"""

    def __init__(self, initial=None):
        self._data = set(initial) if initial else set()
        self._lock = Lock()

    def add(self, item):
        with self._lock:
            self._data.add(item)

    def remove(self, item):
        with self._lock:
            self._data.discard(item)

    def contains(self, item) -> bool:
        with self._lock:
            return item in self._data

    def get_all(self) -> set:
        with self._lock:
            return set(self._data)

    def clear(self):
        with self._lock:
            self._data.clear()

    def __contains__(self, item):
        with self._lock:
            return item in self._data

    def __len__(self):
        with self._lock:
            return len(self._data)


# ============== SCHEDULER UTILITIES ==============

class SafeScheduler:
    """
    Thread-safe scheduler with double-execution prevention.

    Features:
    - Prevents double-execution using persistent state
    - Graceful recovery after restarts
    - Configurable timezone support
    """

    def __init__(self, state_file: Path, logger: logging.Logger = None):
        self.state_file = Path(state_file)
        self.logger = logger or agent_logger
        self._running = False
        self._thread = None

    def _load_state(self) -> Dict:
        """Load scheduler state from file"""
        return safe_json_read(self.state_file, default={
            'last_runs': {},
            'scheduled_tasks': {}
        })

    def _save_state(self, state: Dict):
        """Save scheduler state to file"""
        safe_json_write(self.state_file, state)

    def _should_run(self, task_name: str, min_interval_seconds: float) -> bool:
        """Check if task should run based on last execution time"""
        state = self._load_state()
        last_run = state.get('last_runs', {}).get(task_name)

        if last_run is None:
            return True

        try:
            last_run_time = datetime.fromisoformat(last_run)
            elapsed = (datetime.now() - last_run_time).total_seconds()
            return elapsed >= min_interval_seconds
        except:
            return True

    def _record_run(self, task_name: str):
        """Record that a task has run"""
        def update(state):
            state.setdefault('last_runs', {})[task_name] = datetime.now().isoformat()
            return state
        safe_json_update(self.state_file, update, default={'last_runs': {}})

    def run_daily_at(
        self,
        task_name: str,
        task_func: Callable,
        hour: int,
        minute: int = 0,
        timezone_str: str = "UTC"
    ):
        """
        Run a task daily at a specific time.

        Args:
            task_name: Unique name for the task
            task_func: Function to execute
            hour: Hour to run (0-23)
            minute: Minute to run (0-59)
            timezone_str: Timezone string (e.g., "Europe/London")
        """
        import pytz
        tz = pytz.timezone(timezone_str)

        def scheduler_loop():
            # Minimum 60 seconds between runs of same task
            min_interval = 60

            while self._running:
                try:
                    now = datetime.now(tz)
                    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

                    # If we've passed target time today, schedule for tomorrow
                    if now >= target:
                        target += timedelta(days=1)

                    wait_seconds = (target - now).total_seconds()
                    self.logger.info(f"[{task_name}] Next run at {target}, waiting {wait_seconds/3600:.1f} hours")

                    # Wait in small increments to allow graceful shutdown
                    while wait_seconds > 0 and self._running:
                        sleep_time = min(60, wait_seconds)
                        time.sleep(sleep_time)
                        wait_seconds -= sleep_time

                    if not self._running:
                        break

                    # Check if we should actually run (prevents double-execution)
                    if self._should_run(task_name, min_interval):
                        self.logger.info(f"[{task_name}] Executing scheduled task")
                        try:
                            task_func()
                            self._record_run(task_name)
                            self.logger.info(f"[{task_name}] Task completed successfully")
                        except Exception as e:
                            self.logger.error(f"[{task_name}] Task failed: {e}")
                    else:
                        self.logger.info(f"[{task_name}] Skipping (already ran recently)")

                    # Wait a bit before checking schedule again
                    time.sleep(60)

                except Exception as e:
                    self.logger.error(f"[{task_name}] Scheduler error: {e}")
                    time.sleep(60)

        self._running = True
        self._thread = Thread(target=scheduler_loop, daemon=True, name=f"scheduler_{task_name}")
        self._thread.start()
        self.logger.info(f"[{task_name}] Scheduler started for {hour:02d}:{minute:02d} {timezone_str}")
        return self._thread

    def stop(self):
        """Stop the scheduler"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)


# ============== EXPORTS ==============

__all__ = [
    # Logging
    'setup_logger',
    'agent_logger',

    # File operations
    'FileLock',
    'safe_json_read',
    'safe_json_write',
    'safe_json_update',

    # Retry logic
    'RetryError',
    'retry_with_backoff',
    'call_with_retry',

    # Thread monitoring
    'ThreadHealthMonitor',
    'thread_monitor',

    # Thread-safe data structures
    'ThreadSafeDict',
    'ThreadSafeSet',

    # Scheduler
    'SafeScheduler',
]
