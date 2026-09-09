"""sandbox.yaml 声明式配置。

解析 ``sandbox.yaml`` 文件，提供声明式沙箱配置，
可与 ``@sandbox`` 装饰器或独立使用。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    pass


class SandboxDeclarativeConfig(BaseModel):
    """sandbox.yaml 配置模型。

    Attributes:
        template: 沙箱模板名称。
        timeout: 沙箱超时时间（秒）。
        envs: 环境变量映射。
        python_packages: 需要预安装的 Python 包列表。
        files: 本地→远程文件映射（key=local, value=remote）。
        serializer: 序列化模式，可选 json / pickle / msgpack。
        image: 可选的 Image 对象，会先 build 获取 template id。
            如果同时提供了 image 和 template，image 优先。
        cpu: 沙箱 CPU 核数（传递给 Sandbox.create）。
        memory: 沙箱内存大小 MB（传递给 Sandbox.create）。
    """

    template: str = "code-interpreter-v1"
    timeout: int = 300
    envs: dict[str, str] = Field(default_factory=dict)
    python_packages: list[str] = Field(default_factory=list)
    files: dict[str, str] = Field(default_factory=dict)
    serializer: str = "json"
    image: Any = Field(default=None, exclude=True)
    cpu: int | None = None
    memory: int | None = None

    model_config = {"extra": "ignore"}

    @classmethod
    def from_file(cls, path: str | Path = "sandbox.yaml") -> SandboxDeclarativeConfig:
        """从 YAML 文件加载配置。

        如果文件不存在则返回默认配置。

        Args:
            path: YAML 配置文件路径，默认为当前目录下的 ``sandbox.yaml``。
        """
        path = Path(path)
        if not path.exists():
            return cls()
        try:
            import yaml
        except ImportError as exc:
            raise ImportError(
                "PyYAML is required to load sandbox.yaml: pip install pyyaml"
            ) from exc
        with open(path) as fh:
            data: dict[str, Any] = yaml.safe_load(fh) or {}
        return cls(**data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SandboxDeclarativeConfig:
        """从字典创建配置。"""
        return cls(**data)
