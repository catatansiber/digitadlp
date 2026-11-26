from digitadlp.app.main import create_app


def test_create_app_without_engine(app_settings, monkeypatch):
    monkeypatch.delenv("DIGITADLP_NER", raising=False)
    monkeypatch.delenv("DIGITADLP_NER_PATH", raising=False)
    app = create_app(app_settings)
    assert not hasattr(app.state, "engine")
    app.state.db_engine.dispose()
