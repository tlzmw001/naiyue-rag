import json
from test_model_registry import settings_at


def test_eval_cli_routes_only_to_batch_runner(tmp_path,monkeypatch,capsys):
    import naiyue_rag.cli as cli
    import naiyue_rag.validation.evaluation_run as module
    cfg=settings_at(tmp_path);seen=[]
    def run(settings,questions,output,**kwargs):seen.append((settings,questions,output,kwargs));return 2
    monkeypatch.setattr(module,'run_evaluation',run)
    assert cli.main(['eval','run','--config',cfg.config_path,'--questions','q.jsonl','--output','run-a'])==2
    assert seen[0][0]==cfg and seen[0][1:3]==('q.jsonl','run-a')


def test_eval_help_does_not_create_default_configuration(tmp_path,monkeypatch,capsys):
    import pytest
    from naiyue_rag.cli import main
    monkeypatch.setenv('HOME',str(tmp_path))
    with pytest.raises(SystemExit) as caught:main(['eval','run','--help'])
    assert caught.value.code==0 and not (tmp_path/'.naiyue-rag').exists()


def test_eval_interrupt_outside_query_loop_is_not_success(tmp_path,monkeypatch):
    import naiyue_rag.cli as cli
    import naiyue_rag.validation.evaluation_run as module
    cfg=settings_at(tmp_path)
    def interrupt(*args,**kwargs):raise KeyboardInterrupt()
    monkeypatch.setattr(module,'run_evaluation',interrupt)
    assert cli.main(['eval','run','--config',cfg.config_path,'--questions','q','--output','out'])==130
