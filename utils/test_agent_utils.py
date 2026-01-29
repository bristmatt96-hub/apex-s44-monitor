"""
Test suite for agent utilities
Run with: python -m pytest utils/test_agent_utils.py -v
"""

import os
import sys
import json
import tempfile
import threading
import time
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.agent_utils import (
    FileLock, safe_json_read, safe_json_write, safe_json_update,
    retry_with_backoff, call_with_retry, RetryError,
    ThreadHealthMonitor, ThreadSafeDict, ThreadSafeSet,
    SafeScheduler, setup_logger
)


def test_file_lock():
    """Test file locking mechanism"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        test_file = Path(f.name)
        f.write('{}')

    try:
        # Test that lock can be acquired
        with FileLock(test_file) as lock:
            assert lock is not None

        # Test timeout on lock contention
        results = []

        def hold_lock():
            with FileLock(test_file, timeout=5.0):
                time.sleep(0.5)
                results.append('held')

        def try_lock():
            time.sleep(0.1)  # Let first thread acquire lock
            with FileLock(test_file, timeout=5.0):
                results.append('acquired')

        t1 = threading.Thread(target=hold_lock)
        t2 = threading.Thread(target=try_lock)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert 'held' in results
        assert 'acquired' in results
    finally:
        test_file.unlink(missing_ok=True)
        lock_file = test_file.with_suffix('.json.lock')
        lock_file.unlink(missing_ok=True)


def test_safe_json_operations():
    """Test thread-safe JSON read/write"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        test_file = Path(f.name)

    try:
        # Test write
        data = {"key": "value", "number": 42}
        assert safe_json_write(test_file, data) is True

        # Test read
        result = safe_json_read(test_file)
        assert result == data

        # Test update
        def update_func(d):
            d["new_key"] = "new_value"
            return d

        assert safe_json_update(test_file, update_func) is True

        result = safe_json_read(test_file)
        assert result["new_key"] == "new_value"
        assert result["key"] == "value"

        # Test default value for non-existent file
        result = safe_json_read(Path("/nonexistent/file.json"), default={"default": True})
        assert result == {"default": True}
    finally:
        test_file.unlink(missing_ok=True)
        lock_file = test_file.with_suffix('.json.lock')
        lock_file.unlink(missing_ok=True)


def test_retry_with_backoff():
    """Test retry decorator"""
    call_count = 0

    @retry_with_backoff(max_retries=2, base_delay=0.1)
    def flaky_function():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError("Temporary failure")
        return "success"

    result = flaky_function()
    assert result == "success"
    assert call_count == 3


def test_retry_exhausted():
    """Test that retry raises after max attempts"""
    @retry_with_backoff(max_retries=2, base_delay=0.1)
    def always_fails():
        raise ValueError("Always fails")

    try:
        always_fails()
        assert False, "Should have raised RetryError"
    except RetryError as e:
        assert "failed after" in str(e).lower()


def test_call_with_retry():
    """Test functional retry"""
    call_count = 0

    def flaky_func():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ConnectionError("Temp failure")
        return "ok"

    result = call_with_retry(flaky_func, max_retries=3, base_delay=0.1, exceptions=(ConnectionError,))
    assert result == "ok"
    assert call_count == 2


def test_thread_safe_dict():
    """Test thread-safe dictionary"""
    d = ThreadSafeDict({"initial": "value"})

    assert d.get("initial") == "value"
    assert d.get("missing", "default") == "default"

    d.set("new_key", "new_value")
    assert d.get("new_key") == "new_value"

    d.update({"a": 1, "b": 2})
    assert d.get("a") == 1
    assert d.get("b") == 2

    assert "a" in d
    assert "missing" not in d

    d.delete("a")
    assert "a" not in d


def test_thread_safe_set():
    """Test thread-safe set"""
    s = ThreadSafeSet([1, 2, 3])

    assert 1 in s
    assert 4 not in s

    s.add(4)
    assert 4 in s

    s.remove(1)
    assert 1 not in s

    assert len(s) == 3


def test_thread_health_monitor():
    """Test thread health monitoring"""
    monitor = ThreadHealthMonitor()

    completed = threading.Event()

    def worker():
        for _ in range(5):
            monitor.heartbeat("test_worker")
            time.sleep(0.1)
        completed.set()

    monitor.register_thread(
        name="test_worker",
        target=worker,
        heartbeat_timeout=2.0,
        auto_restart=False,
        daemon=True
    )

    # Check initial health
    time.sleep(0.2)
    status = monitor.get_health_status()
    assert "test_worker" in status
    assert status["test_worker"]["alive"] is True

    # Wait for completion
    completed.wait(timeout=2.0)
    time.sleep(0.2)

    status = monitor.get_health_status()
    assert status["test_worker"]["status"] == "completed"


def test_concurrent_json_writes():
    """Test that concurrent JSON writes don't corrupt data"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        test_file = Path(f.name)

    try:
        # Initialize file
        safe_json_write(test_file, {"count": 0})

        def increment():
            for _ in range(10):
                def update(d):
                    d["count"] = d.get("count", 0) + 1
                    return d
                safe_json_update(test_file, update, default={"count": 0})

        threads = [threading.Thread(target=increment) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        result = safe_json_read(test_file)
        # Should have exactly 50 increments
        assert result["count"] == 50
    finally:
        test_file.unlink(missing_ok=True)
        lock_file = test_file.with_suffix('.json.lock')
        lock_file.unlink(missing_ok=True)


if __name__ == "__main__":
    print("Running agent utilities tests...")

    tests = [
        test_file_lock,
        test_safe_json_operations,
        test_retry_with_backoff,
        test_retry_exhausted,
        test_call_with_retry,
        test_thread_safe_dict,
        test_thread_safe_set,
        test_thread_health_monitor,
        test_concurrent_json_writes,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            print(f"  PASS: {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL: {test.__name__} - {e}")
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
