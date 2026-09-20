"""Environment-variable defaults for judge selection (.env.example).

These are consulted ONLY when a profile omits the corresponding config key
-- profile config always overrides the environment. See .env.example and
docs/MODEL-SETUP.md.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from amplifier_fast_decisions.contracts import Policy
from amplifier_fast_decisions.demo import DemoCoordinator
from amplifier_fast_decisions.local_backend import HostedBackend, OllamaBackend
from amplifier_fast_decisions.runtime import get_runtime


class JudgeEnvDefaultTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_ollama_selected_via_env_when_backend_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ,
                {"FAST_DECISIONS_JUDGE": "local", "FAST_DECISIONS_LOCAL_HOST": "ollama"},
            ):
                runtime, _ = get_runtime(DemoCoordinator(), {"events_dir": tmp})
            try:
                self.assertIsInstance(runtime.service.backend, OllamaBackend)
            finally:
                await runtime.close()

    async def test_local_defaults_to_ollama_without_local_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"FAST_DECISIONS_JUDGE": "local"}):
                os.environ.pop("FAST_DECISIONS_LOCAL_HOST", None)
                runtime, _ = get_runtime(DemoCoordinator(), {"events_dir": tmp})
            try:
                self.assertIsInstance(runtime.service.backend, OllamaBackend)
            finally:
                await runtime.close()

    async def test_hosted_selected_via_env_with_model_and_token_env_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ,
                {
                    "FAST_DECISIONS_JUDGE": "hosted",
                    "FAST_DECISIONS_HOSTED_URL": "https://hosted.example/v1",
                    "FAST_DECISIONS_HOSTED_MODEL": "env-model",
                    "FAST_DECISIONS_HOSTED_TOKEN": "env-token",
                },
            ):
                runtime, _ = get_runtime(DemoCoordinator(), {"events_dir": tmp})
            try:
                self.assertIsInstance(runtime.service.backend, HostedBackend)
                self.assertEqual(runtime.service.backend.model, "env-model")
                self.assertEqual(runtime.service.backend.api_key, "env-token")
            finally:
                await runtime.close()

    async def test_profile_backend_overrides_env_judge(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"FAST_DECISIONS_JUDGE": "hosted"}):
                runtime, _ = get_runtime(
                    DemoCoordinator(), {"backend": "deterministic", "events_dir": tmp}
                )
            try:
                self.assertEqual(runtime.service.backend.name, "scripted-demo")
            finally:
                await runtime.close()

    async def test_local_model_env_used_as_ollama_model_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"FAST_DECISIONS_LOCAL_MODEL": "env-qwen"}):
                runtime, _ = get_runtime(
                    DemoCoordinator(), {"backend": "ollama", "events_dir": tmp}
                )
            try:
                self.assertEqual(runtime.service.backend.model, "env-qwen")
            finally:
                await runtime.close()

    async def test_profile_model_overrides_local_model_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"FAST_DECISIONS_LOCAL_MODEL": "env-qwen"}):
                runtime, _ = get_runtime(
                    DemoCoordinator(),
                    {"backend": "ollama", "model": "profile-qwen", "events_dir": tmp},
                )
            try:
                self.assertEqual(runtime.service.backend.model, "profile-qwen")
            finally:
                await runtime.close()


class AllowExternalStateEnvDefaultTests(unittest.TestCase):
    def test_env_true_sets_default_when_config_omits_field(self):
        with mock.patch.dict(os.environ, {"FAST_DECISIONS_ALLOW_EXTERNAL_STATE": "true"}):
            policy = Policy.from_config({})
        self.assertTrue(policy.allow_external_state)

    def test_env_false_leaves_default_false(self):
        with mock.patch.dict(os.environ, {"FAST_DECISIONS_ALLOW_EXTERNAL_STATE": "false"}):
            policy = Policy.from_config({})
        self.assertFalse(policy.allow_external_state)

    def test_absent_env_leaves_dataclass_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FAST_DECISIONS_ALLOW_EXTERNAL_STATE", None)
            policy = Policy.from_config({})
        self.assertFalse(policy.allow_external_state)

    def test_config_value_overrides_env(self):
        with mock.patch.dict(os.environ, {"FAST_DECISIONS_ALLOW_EXTERNAL_STATE": "true"}):
            policy = Policy.from_config({"allow_external_state": False})
        self.assertFalse(policy.allow_external_state)


if __name__ == "__main__":
    unittest.main()
