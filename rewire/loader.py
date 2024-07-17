import os
from pathlib import Path

from loguru import logger
from rewire.config import parse_file
from rewire.space import Module
from anyio.to_thread import run_sync


class LoaderModule(Module):
    queue: list[str] = []

    def add(self, *module: str):
        self.queue.extend(module)
        return self

    async def load(self):
        await run_sync(self._load)

    def discover(self):
        from rewire.plugins import PluginConfig

        config = PluginConfig.model_validate(parse_file(".plugin.yaml", True))
        self.queue.extend(config.include)
        return self

    def _load(self):
        from rewire.plugins import PluginConfig

        while self.queue:
            module = self.queue.pop()

            dir = Path(module.replace(".", "/").strip("/"))
            for file in sorted(os.listdir(dir)):
                if file.startswith("_"):
                    continue
                loc = dir / file
                is_plugin_dir = loc.is_dir() and (loc / "__init__.py").exists()

                if file.endswith(".py") or is_plugin_dir:
                    self.load_file(module, file)
                if is_plugin_dir and (cfg := dir / ".plugin.yaml").exists():
                    config = PluginConfig.model_validate(parse_file(cfg, True))
                    for include in config.include:
                        self.queue.append(f"{module}.{file}.{include}")

            if (directory_config := dir / ".plugin.yaml").exists():
                config = PluginConfig.model_validate(parse_file(directory_config, True))
                for include in config.include:
                    self.queue.append(f"{module}.{include}")

    def load_file(self, module: str, file: str):
        file = file.removesuffix(".py")
        logger.info(f"importing {module}.{file}")
        exec(f"import {module}.{file} as module;")
