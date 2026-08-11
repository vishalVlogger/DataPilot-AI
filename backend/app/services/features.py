from app.core.config import get_settings


class FeatureFlags:
    def enabled(self, name: str) -> bool:
        field = f"feature_{name}"
        if not hasattr(get_settings(), field): raise KeyError(name)
        return bool(getattr(get_settings(), field))


feature_flags = FeatureFlags()
