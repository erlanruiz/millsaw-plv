"""Smoke tests for the saws/registry module (no actual FTP traffic)."""

from millsaw.saws import Saw, SawList, SawRegistry, SendError


def test_registry_round_trip(tmp_path):
    reg = SawRegistry(tmp_path)
    # Fresh registry is empty
    assert reg.load().saws == []

    saws = SawList(saws=[
        Saw(name="ChopSaw1", host="192.0.2.50", port=2121,
            username="millsaw", password="",
            remote_dir="/", passive=True, timeout_sec=30),
        Saw(name="ChopSaw2", host="192.0.2.51", port=21,
            username="ftpuser", password="",
            remote_dir="/incoming", passive=False, timeout_sec=60),
    ])
    reg.save(saws)
    reloaded = reg.load()
    assert len(reloaded.saws) == 2
    assert reloaded.find("ChopSaw1").host == "192.0.2.50"
    assert reloaded.find("ChopSaw2").remote_dir == "/incoming"
    assert reloaded.find("ChopSaw2").passive is False


def test_registry_tolerates_garbage(tmp_path):
    p = tmp_path / "saws.json"
    p.write_text("not valid json", encoding="utf-8")
    assert SawRegistry(tmp_path).load().saws == []
