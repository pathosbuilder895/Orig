# Quick patch to fix ALLOWED_ORIGINS parsing
# Replace the field definition to use a string instead of List[str]
# Then convert it in a validator

import sys

# Read the original config.py
with open('original/core/config.py', 'r') as f:
    content = f.read()

# Replace the problematic field definition and validator
old_definition = '''    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8080"]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",")]
        return v'''

new_definition = '''    _ALLOWED_ORIGINS_STR: str = "http://localhost:3000,http://localhost:8080"
    
    @property
    def ALLOWED_ORIGINS(self) -> List[str]:
        """Parse comma-separated origins string into list."""
        if isinstance(self._ALLOWED_ORIGINS_STR, str):
            return [o.strip() for o in self._ALLOWED_ORIGINS_STR.split(",")]
        return self._ALLOWED_ORIGINS_STR'''

content = content.replace(old_definition, new_definition)

# Write back
with open('original/core/config.py', 'w') as f:
    f.write(content)

print("Patched config.py")
