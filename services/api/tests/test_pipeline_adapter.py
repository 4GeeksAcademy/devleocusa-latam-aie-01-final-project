from pathlib import Path


def test_approval_module_loads_from_local_pipeline_source():
    from src.pipeline_adapter import _approval_module

    module = _approval_module()
    module_path = Path(module.__file__).resolve()

    assert module.__name__ == "rfp_intake.approval"
    assert module_path.name == "approval.py"
    assert module_path.parent.name == "rfp_intake"
    assert module_path.parents[1].name == "src"
    assert module_path.parents[2].name == "pipelines"