import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import zipfile

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "skills"))

import app_builder  # noqa: E402
import comfyui_client  # noqa: E402
import youtube_analytics  # noqa: E402
import youtube_studio  # noqa: E402


class TestSkillsContract(unittest.TestCase):
    def test_all_skills_help_and_schema(self):
        skill_files = [
            "blender_render.py",
            "compile_android.py",
            "test_android.py",
            "unity_build.py",
            "youtube_analytics.py",
            "comfyui_client.py",
            "youtube_studio.py",
            "app_builder.py",
        ]
        for fname in skill_files:
            path = ROOT_DIR / "skills" / fname
            res_help = subprocess.run([sys.executable, str(path), "--help"], capture_output=True, text=True)
            self.assertEqual(res_help.returncode, 0, msg=f"{fname} --help failed: {res_help.stderr}")

            res_schema = subprocess.run([sys.executable, str(path), "--schema"], capture_output=True, text=True)
            self.assertEqual(res_schema.returncode, 0, msg=f"{fname} --schema failed: {res_schema.stderr}")
            schema_json = json.loads(res_schema.stdout)
            self.assertEqual(schema_json.get("title"), "AtlasSkillReport")


class TestYoutubeAnalytics(unittest.TestCase):
    def test_missing_api_key_returns_valid_failed_json(self):
        env = dict(os.environ)
        env["YOUTUBE_API_KEY"] = ""
        res = subprocess.run(
            [sys.executable, str(ROOT_DIR / "skills" / "youtube_analytics.py"), "--action", "trending_niche", "--query", "AI"],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(res.returncode, 0)
        rep = json.loads(res.stdout)
        self.assertEqual(rep["status"], "failed")
        self.assertIn("YOUTUBE_API_KEY", rep["summary"])

    def test_trending_niche_virality_sorting(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "yt.log"
            mock_client = MagicMock()
            mock_client.get.side_effect = [
                SimpleNamespace(
                    raise_for_status=lambda: None,
                    json=lambda: {"items": [{"id": {"videoId": "v1"}}, {"id": {"videoId": "v2"}}]},
                ),
                SimpleNamespace(
                    raise_for_status=lambda: None,
                    json=lambda: {
                        "items": [
                            {
                                "id": "v1",
                                "snippet": {"title": "Video 1", "channelId": "c1", "channelTitle": "Ch1", "publishedAt": "2026-11-10T00:00:00Z", "tags": ["ai"]},
                                "statistics": {"viewCount": "10000", "likeCount": "500", "commentCount": "20"},
                            },
                            {
                                "id": "v2",
                                "snippet": {"title": "Video 2", "channelId": "c2", "channelTitle": "Ch2", "publishedAt": "2026-11-11T00:00:00Z", "tags": ["tech"]},
                                "statistics": {"viewCount": "50000", "likeCount": "2000", "commentCount": "100"},
                            },
                        ]
                    },
                ),
                SimpleNamespace(
                    raise_for_status=lambda: None,
                    json=lambda: {
                        "items": [
                            {"id": "c1", "statistics": {"subscriberCount": "1000"}},   # virality = 10.0
                            {"id": "c2", "statistics": {"subscriberCount": "100000"}}, # virality = 0.5
                        ]
                    },
                ),
            ]
            data = youtube_analytics._trending_niche(mock_client, "key", "AI", 14, 10, log_file)
            self.assertEqual(data["count"], 2)
            self.assertEqual(data["topics"][0]["video_id"], "v1")
            self.assertEqual(data["topics"][0]["virality_ratio"], 10.0)


class TestComfyUIClient(unittest.TestCase):
    def test_offline_fallback(self):
        res = comfyui_client.ping_comfyui("")
        self.assertEqual(res["status"], "offline")
        self.assertEqual(res["fallback"], "local_assets")

        res_unreach = comfyui_client.ping_comfyui("http://127.0.0.1:59999", timeout=0.5)
        self.assertEqual(res_unreach["status"], "offline")
        self.assertEqual(res_unreach["fallback"], "local_assets")

    def test_cli_offline_does_not_crash(self):
        env = dict(os.environ)
        env["COMFYUI_API_URL"] = ""
        res = subprocess.run(
            [sys.executable, str(ROOT_DIR / "skills" / "comfyui_client.py"), "--action", "ping"],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(res.returncode, 0)
        rep = json.loads(res.stdout)
        self.assertEqual(rep["status"], "partial")
        self.assertEqual(rep["artifacts"]["comfyui_status"], {"status": "offline", "fallback": "local_assets"})


class TestYoutubeStudio(unittest.TestCase):
    def test_missing_script_returns_failed_json(self):
        res = subprocess.run(
            [sys.executable, str(ROOT_DIR / "skills" / "youtube_studio.py")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        rep = json.loads(res.stdout)
        self.assertEqual(rep["status"], "failed")

    def test_vtt_to_srt_and_subtitles_fallback(self):
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.500\nПривет мир\n"
        srt = youtube_studio._vtt_to_srt(vtt)
        self.assertIn("00:00:00,000 --> 00:00:02,500", srt)
        self.assertIn("Привет мир", srt)

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            vtt_path = p / "voice.vtt"
            vtt_path.write_text(vtt, encoding="utf-8")
            srt_out = p / "out.srt"
            log_file = p / "studio.log"
            with patch.dict(sys.modules, {"faster_whisper": None}):
                engine = youtube_studio._generate_subtitles(p / "voice.mp3", vtt_path, "Привет мир", srt_out, log_file)
            self.assertEqual(engine, "edge-tts-subtitles")
            self.assertTrue(srt_out.exists())

    def test_detect_encoder_fallback_to_libx264(self):
        with patch.object(youtube_studio.subprocess, "run", side_effect=FileNotFoundError("no nvidia-smi")):
            self.assertEqual(youtube_studio._detect_video_encoder(), "libx264")


class TestAppBuilder(unittest.TestCase):
    def test_python_project_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "hello.py").write_text("print('ok')\n", encoding="utf-8")
            rep = app_builder._build_python(p, p / "build.log")
            self.assertEqual(rep["status"], "success")

    def test_android_missing_gradle_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            rep = app_builder._build_android(p, p / "artifacts", p / "build.log")
            self.assertEqual(rep["status"], "failed")
            self.assertIn("Gradle", rep["summary"])

    def test_android_dex_check_and_timestamped_apk(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "settings.gradle.kts").write_text("", encoding="utf-8")
            (p / "build.gradle.kts").write_text("", encoding="utf-8")
            apk_dir = p / "app" / "build" / "outputs" / "apk" / "debug"
            apk_dir.mkdir(parents=True)
            apk_file = apk_dir / "app-debug.apk"
            with zipfile.ZipFile(apk_file, "w") as zf:
                zf.writestr("classes.dex", b"dex\n035\x00")
                zf.writestr("AndroidManifest.xml", b"<manifest/>")

            artifacts_dir = p / "artifacts"
            with patch.object(app_builder.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="BUILD SUCCESSFUL")):
                rep = app_builder._build_android(p, artifacts_dir, p / "build.log")

            self.assertEqual(rep["status"], "success")
            out_apk = Path(rep["artifacts"]["apk"])
            self.assertTrue(out_apk.exists())
            self.assertTrue(out_apk.name.startswith("app-debug_"))
            self.assertTrue(out_apk.name.endswith(".apk"))


if __name__ == "__main__":
    unittest.main()
