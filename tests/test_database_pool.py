"""Process-wide PostgreSQL pool ownership."""

from fastfunnel.domain import store


def test_postgres_pool_is_singleton_per_url(monkeypatch):
    created = []

    class FakePool:
        check_connection = staticmethod(lambda connection: None)

        def __init__(self, **kwargs):
            created.append(kwargs)

        def open(self):
            pass

        def close(self):
            pass

    store.close_postgres_pools()
    monkeypatch.setattr(store, "ConnectionPool", FakePool)
    first = store._postgres_pool("postgresql://example/one")
    second = store._postgres_pool("postgresql://example/one")
    other = store._postgres_pool("postgresql://example/two")

    assert first is second
    assert other is not first
    assert len(created) == 2
    assert created[0]["min_size"] == 0
    assert created[0]["max_size"] == 3
    store.close_postgres_pools()
