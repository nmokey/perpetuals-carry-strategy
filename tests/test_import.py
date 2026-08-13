"""M0-T1/M0-T3 acceptance: the package and the compiled extension both import."""

import perpcarry


def test_package_imports_with_version():
    assert perpcarry.__version__


def test_extension_module_imports_and_matches_version():
    import perpcarry_cpp

    assert perpcarry_cpp.version() == perpcarry.__version__
