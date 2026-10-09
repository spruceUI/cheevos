from cheevos.core.local_games import local_games, on_device_game_ids
from cheevos.core.models import LocalGame
from cheevos.core.proxy import ProxyReader
from cheevos.platform.paths import Paths


def write_proxy_ids(paths, text):
    paths.proxy_data_dir.mkdir(parents=True, exist_ok=True)
    (paths.proxy_data_dir / "cached_game_ids.txt").write_text(text)


def test_nothing_known(tmp_path):
    paths = Paths(sdcard=tmp_path)
    assert local_games(ProxyReader(paths)) == []


def test_proxy_ids(tmp_path):
    paths = Paths(sdcard=tmp_path)
    write_proxy_ids(paths, "1446\n519\n²\n\n")
    assert local_games(ProxyReader(paths)) == [
        LocalGame(519, "", "", "raofflineproxy"),
        LocalGame(1446, "", "", "raofflineproxy"),
    ]
    assert on_device_game_ids(ProxyReader(paths)) == {519, 1446}


def test_stale_pyui_cache_is_ignored(tmp_path):
    paths = Paths(sdcard=tmp_path)
    stale = tmp_path / "Saves" / "pyui-cheevos-cache.json"
    stale.parent.mkdir(parents=True)
    stale.write_text('[{"rom_file_path": "/mnt/SDCARD/Roms/GBA/x.gba", "game_id": 519}]')
    write_proxy_ids(paths, "7\n")
    assert on_device_game_ids(ProxyReader(paths)) == {7}
