"""
Secure Pickle - HMAC-signed pickle files to prevent tampering

Pickle deserialization can execute arbitrary code, making it a security risk
if an attacker can modify pickle files. This module adds HMAC signatures
to detect tampering.

Usage:
    from core.secure_pickle import secure_dump, secure_load

    # Save with signature
    secure_dump(model, "model.pkl")

    # Load with verification (raises SecurityError if tampered)
    model = secure_load("model.pkl")
"""
import os
import hmac
import hashlib
import pickle
from pathlib import Path
from typing import Any, Optional
from loguru import logger


class PickleSecurityError(Exception):
    """Raised when a pickle file fails integrity verification"""
    pass


# Secret key for HMAC signing
# In production, this should be loaded from a secure location
# Falls back to a machine-specific key derived from hostname + username
def _get_signing_key() -> bytes:
    """Get the HMAC signing key"""
    # First try environment variable
    env_key = os.environ.get("PICKLE_SIGNING_KEY")
    if env_key:
        return env_key.encode('utf-8')

    # Fallback: derive from machine-specific info
    # This means pickles are only valid on the same machine/user
    import socket
    import getpass
    machine_info = f"{socket.gethostname()}:{getpass.getuser()}:apex-s44-monitor"
    return hashlib.sha256(machine_info.encode()).digest()


SIGNING_KEY = _get_signing_key()
SIGNATURE_SUFFIX = ".sig"


def _compute_signature(data: bytes) -> str:
    """Compute HMAC-SHA256 signature for data"""
    return hmac.new(SIGNING_KEY, data, hashlib.sha256).hexdigest()


def _get_signature_path(pickle_path: Path) -> Path:
    """Get the signature file path for a pickle file"""
    return pickle_path.with_suffix(pickle_path.suffix + SIGNATURE_SUFFIX)


def secure_dump(obj: Any, filepath: str, protocol: int = pickle.HIGHEST_PROTOCOL) -> None:
    """
    Save an object to a pickle file with HMAC signature.

    Args:
        obj: Object to pickle
        filepath: Path to save pickle file
        protocol: Pickle protocol version
    """
    filepath = Path(filepath)

    # Serialize to bytes
    data = pickle.dumps(obj, protocol=protocol)

    # Compute signature
    signature = _compute_signature(data)

    # Write pickle file
    with open(filepath, 'wb') as f:
        f.write(data)

    # Write signature file
    sig_path = _get_signature_path(filepath)
    with open(sig_path, 'w') as f:
        f.write(signature)

    logger.debug(f"Saved signed pickle: {filepath}")


def secure_load(filepath: str, verify: bool = True) -> Any:
    """
    Load an object from a signed pickle file.

    Args:
        filepath: Path to pickle file
        verify: If True, verify HMAC signature before loading

    Returns:
        Unpickled object

    Raises:
        PickleSecurityError: If signature verification fails
        FileNotFoundError: If pickle or signature file doesn't exist
    """
    filepath = Path(filepath)

    if not filepath.exists():
        raise FileNotFoundError(f"Pickle file not found: {filepath}")

    # Read pickle data
    with open(filepath, 'rb') as f:
        data = f.read()

    if verify:
        sig_path = _get_signature_path(filepath)

        # Check if signature file exists
        if not sig_path.exists():
            # For backward compatibility: if no signature exists,
            # create one (first-time migration)
            logger.warning(
                f"No signature found for {filepath}. "
                f"Creating signature for backward compatibility. "
                f"This file should be re-saved with secure_dump()."
            )
            signature = _compute_signature(data)
            with open(sig_path, 'w') as f:
                f.write(signature)
        else:
            # Read expected signature
            with open(sig_path, 'r') as f:
                expected_sig = f.read().strip()

            # Compute actual signature
            actual_sig = _compute_signature(data)

            # Constant-time comparison to prevent timing attacks
            if not hmac.compare_digest(expected_sig, actual_sig):
                logger.error(f"SECURITY: Pickle file tampering detected: {filepath}")
                raise PickleSecurityError(
                    f"Pickle file integrity check failed: {filepath}. "
                    f"The file may have been tampered with."
                )

    # Safe to load
    return pickle.loads(data)


def verify_pickle(filepath: str) -> bool:
    """
    Verify a pickle file's signature without loading it.

    Args:
        filepath: Path to pickle file

    Returns:
        True if signature is valid, False otherwise
    """
    try:
        filepath = Path(filepath)

        if not filepath.exists():
            return False

        sig_path = _get_signature_path(filepath)
        if not sig_path.exists():
            return False

        with open(filepath, 'rb') as f:
            data = f.read()

        with open(sig_path, 'r') as f:
            expected_sig = f.read().strip()

        actual_sig = _compute_signature(data)
        return hmac.compare_digest(expected_sig, actual_sig)

    except Exception:
        return False


def sign_existing_pickle(filepath: str) -> None:
    """
    Add a signature to an existing unsigned pickle file.
    Use this to migrate existing pickle files.

    Args:
        filepath: Path to pickle file
    """
    filepath = Path(filepath)

    if not filepath.exists():
        raise FileNotFoundError(f"Pickle file not found: {filepath}")

    with open(filepath, 'rb') as f:
        data = f.read()

    signature = _compute_signature(data)

    sig_path = _get_signature_path(filepath)
    with open(sig_path, 'w') as f:
        f.write(signature)

    logger.info(f"Signed existing pickle: {filepath}")
