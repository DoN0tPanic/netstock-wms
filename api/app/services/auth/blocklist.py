"""Common weak passwords rejected by the local password policy.

Curated subset (not the full 10k list from a copyrighted breach corpus, to
avoid licensing ambiguity (§9.1 alternative): "lista
generata internamente"). Expand this list in docs/06-security.md if a larger
company-approved corpus becomes available.
"""

COMMON_PASSWORDS: frozenset[str] = frozenset(
    {
        "password", "password1", "password123", "12345678", "123456789",
        "1234567890", "qwerty123", "qwertyuiop", "letmein123", "welcome123",
        "admin1234", "administrator", "changeme123", "changeme1", "iloveyou1",
        "abc123456", "football1", "baseball1", "dragon123", "monkey123",
        "master123", "shadow123", "superman1", "trustno1a", "sunshine1",
        "princess1", "passw0rd1", "p@ssw0rd1", "p@ssword1", "1qaz2wsx3edc",
        "qwerty1234", "azerty123", "1234qwer", "starwars1", "letmein1234",
        "welcome1234", "network123", "cisco12345", "network1234", "warehouse1",
        "magazzino1", "italia1234", "password!1", "companyname1", "changeit123",
        "temporary1", "default123", "guest12345", "root1234567", "toor123456",
    }
)


def is_common_password(plain: str) -> bool:
    return plain.strip().lower() in COMMON_PASSWORDS
