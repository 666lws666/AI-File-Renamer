"""Credential Manager — secure API key storage using Windows Credential Manager.

Uses the keyring library which on Windows automatically backs to
Windows Credential Manager (CredRead/CredWrite).
"""

from loguru import logger

SERVICE_NAME: str = "AIRenamer"
ACCOUNT_NAME: str = "api_key"


def get_credential(service: str = SERVICE_NAME, account: str = ACCOUNT_NAME) -> str | None:
    """Retrieve a credential from the OS keychain.

    Returns None if the credential does not exist or cannot be read.
    """
    try:
        import keyring
        return keyring.get_password(service, account)
    except Exception as e:
        logger.warning(f"无法从凭据管理器读取: {e}")
        return None


def get_credential_strict(
    service: str = SERVICE_NAME, account: str = ACCOUNT_NAME
) -> str | None:
    """Retrieve a credential while preserving backend read failures.

    Transactional callers must distinguish a missing credential from an
    unavailable credential backend; swallowing that distinction can destroy
    the previous secret during compensation.
    """
    import keyring

    return keyring.get_password(service, account)


def set_credential(
    secret: str,
    service: str = SERVICE_NAME,
    account: str = ACCOUNT_NAME,
) -> bool:
    """Store a credential in the OS keychain.

    Returns True on success, False on failure.
    Deletes the credential if secret is empty.
    """
    try:
        import keyring
        if secret:
            keyring.set_password(service, account, secret)
            logger.debug("凭据已保存到系统凭据管理器")
        else:
            _delete_credential(service, account)
        return True
    except Exception as e:
        logger.error(f"无法保存凭据: {e}")
        return False


def delete_credential(service: str = SERVICE_NAME, account: str = ACCOUNT_NAME) -> bool:
    """Delete a credential from the OS keychain.

    Returns True on success (including if it didn't exist), False on failure.
    """
    try:
        _delete_credential(service, account)
        return True
    except Exception as e:
        logger.error(f"无法删除凭据: {e}")
        return False


def _delete_credential(service: str, account: str) -> None:
    """Internal helper — delete with graceful handling for missing creds."""
    import keyring
    try:
        keyring.delete_password(service, account)
        logger.debug("凭据已从系统凭据管理器删除")
    except keyring.errors.PasswordDeleteError:
        # Credential doesn't exist — that's fine
        logger.debug("凭据不存在，无需删除")
