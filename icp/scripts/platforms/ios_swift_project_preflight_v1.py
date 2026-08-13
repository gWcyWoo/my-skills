from platforms import inactive_platform_core_v1 as _core


def preflight(project_root):
    return _core.preflight("ios-swift", "ios-swift-standard", project_root)


def inspect_entry_requirements(project_root):
    return _core.inspect_entry_requirements("ios-swift", "ios-swift-standard", project_root)
