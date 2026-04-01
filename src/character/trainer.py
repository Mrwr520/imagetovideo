"""角色 LoRA 训练模块。

提供 LoRA 训练接口，支持 kohya_ss 和 SimpleTuner 训练脚本。
针对 8GB 显存优化训练参数。
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# 8GB 显存优化参数
_LOW_VRAM_CONFIG = {
    "resolution": 512,
    "batch_size": 1,
    "gradient_accumulation": 4,
    "mixed_precision": "fp16",
    "gradient_checkpointing": True,
    "optimizer": "adamw8bit",
    "network_dim": 32,
    "network_alpha": 16,
    "max_train_steps": 1000,
    "learning_rate": 1e-4,
    "unet_lr": 1e-4,
    "text_encoder_lr": 5e-5,
}

# 标准配置（16GB+ 显存）
_STANDARD_CONFIG = {
    "resolution": 768,
    "batch_size": 2,
    "gradient_accumulation": 2,
    "mixed_precision": "fp16",
    "gradient_checkpointing": False,
    "optimizer": "adamw",
    "network_dim": 64,
    "network_alpha": 32,
    "max_train_steps": 2000,
    "learning_rate": 1e-4,
    "unet_lr": 1e-4,
    "text_encoder_lr": 5e-5,
}


@dataclass
class TrainingConfig:
    """LoRA 训练配置。"""
    
    # 基础配置
    character_name: str
    training_images_dir: Path
    output_dir: Path
    base_model: str = "stabilityai/stable-diffusion-xl-base-1.0"
    
    # 训练参数
    resolution: int = 512
    batch_size: int = 1
    gradient_accumulation: int = 4
    max_train_steps: int = 1000
    learning_rate: float = 1e-4
    
    # LoRA 参数
    network_dim: int = 32
    network_alpha: int = 16
    
    # 优化参数
    mixed_precision: str = "fp16"
    gradient_checkpointing: bool = True
    optimizer: str = "adamw8bit"
    
    # 触发词
    trigger_word: str = ""
    
    def to_dict(self) -> dict:
        return {
            "character_name": self.character_name,
            "training_images_dir": str(self.training_images_dir),
            "output_dir": str(self.output_dir),
            "base_model": self.base_model,
            "resolution": self.resolution,
            "batch_size": self.batch_size,
            "gradient_accumulation": self.gradient_accumulation,
            "max_train_steps": self.max_train_steps,
            "learning_rate": self.learning_rate,
            "network_dim": self.network_dim,
            "network_alpha": self.network_alpha,
            "mixed_precision": self.mixed_precision,
            "gradient_checkpointing": self.gradient_checkpointing,
            "optimizer": self.optimizer,
            "trigger_word": self.trigger_word,
        }


@dataclass
class TrainingProgress:
    """训练进度。"""
    
    current_step: int = 0
    total_steps: int = 0
    loss: float = 0.0
    learning_rate: float = 0.0
    elapsed_time: float = 0.0
    eta: float = 0.0
    status: str = "pending"  # pending, running, completed, failed
    error: str = ""
    
    @property
    def progress_percent(self) -> float:
        if self.total_steps == 0:
            return 0.0
        return (self.current_step / self.total_steps) * 100


@dataclass
class TrainingResult:
    """训练结果。"""
    
    success: bool
    lora_path: Path | None = None
    config: TrainingConfig | None = None
    final_loss: float = 0.0
    total_time: float = 0.0
    error: str = ""
    metadata: dict = field(default_factory=dict)


class LoRATrainer:
    """LoRA 训练器。"""
    
    def __init__(
        self,
        vram_limit: int = 8192,
        kohya_path: str = "",
        simpletuner_path: str = "",
    ) -> None:
        """初始化训练器。
        
        Args:
            vram_limit: 显存限制（MB）。
            kohya_path: kohya_ss 脚本路径。
            simpletuner_path: SimpleTuner 脚本路径。
        """
        self._vram_limit = vram_limit
        self._kohya_path = Path(kohya_path) if kohya_path else None
        self._simpletuner_path = Path(simpletuner_path) if simpletuner_path else None
        self._current_process: subprocess.Popen | None = None
        self._progress = TrainingProgress()
    
    def _is_low_vram_mode(self) -> bool:
        """判断是否启用低显存模式。"""
        return self._vram_limit <= 8192
    
    def get_recommended_config(self, character_name: str, images_dir: Path) -> TrainingConfig:
        """获取推荐的训练配置。
        
        Args:
            character_name: 角色名。
            images_dir: 训练图片目录。
            
        Returns:
            推荐的训练配置。
        """
        base_config = _LOW_VRAM_CONFIG if self._is_low_vram_mode() else _STANDARD_CONFIG
        
        output_dir = Path("models/lora") / character_name
        
        return TrainingConfig(
            character_name=character_name,
            training_images_dir=images_dir,
            output_dir=output_dir,
            trigger_word=f"<{character_name}>",
            **base_config,
        )
    
    def _prepare_dataset(self, config: TrainingConfig) -> Path:
        """准备训练数据集。
        
        Args:
            config: 训练配置。
            
        Returns:
            数据集目录路径。
        """
        dataset_dir = Path(tempfile.mkdtemp(prefix="lora_dataset_"))
        
        # 创建 kohya 格式的数据集结构
        # {repeats}_{trigger_word}
        repeats = 10
        trigger = config.trigger_word.strip("<>") or config.character_name
        subset_dir = dataset_dir / f"{repeats}_{trigger}"
        subset_dir.mkdir(parents=True, exist_ok=True)
        
        # 复制训练图片
        images_dir = Path(config.training_images_dir)
        if images_dir.exists():
            for img_file in images_dir.iterdir():
                if img_file.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                    dest = subset_dir / img_file.name
                    dest.write_bytes(img_file.read_bytes())
                    
                    # 创建对应的 caption 文件
                    caption_file = dest.with_suffix(".txt")
                    caption_file.write_text(
                        f"{config.trigger_word}, anime style, high quality",
                        encoding="utf-8",
                    )
        
        return dataset_dir


    def _build_kohya_command(self, config: TrainingConfig, dataset_dir: Path) -> list[str]:
        """构建 kohya_ss 训练命令。"""
        output_dir = Path(config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            "python",
            str(self._kohya_path / "sdxl_train_network.py") if self._kohya_path else "sdxl_train_network.py",
            f"--pretrained_model_name_or_path={config.base_model}",
            f"--train_data_dir={dataset_dir}",
            f"--output_dir={output_dir}",
            f"--output_name={config.character_name}_lora",
            f"--resolution={config.resolution}",
            f"--train_batch_size={config.batch_size}",
            f"--gradient_accumulation_steps={config.gradient_accumulation}",
            f"--max_train_steps={config.max_train_steps}",
            f"--learning_rate={config.learning_rate}",
            f"--network_module=networks.lora",
            f"--network_dim={config.network_dim}",
            f"--network_alpha={config.network_alpha}",
            f"--mixed_precision={config.mixed_precision}",
            f"--optimizer_type={config.optimizer}",
            "--save_model_as=safetensors",
            "--cache_latents",
            "--cache_latents_to_disk",
        ]
        
        if config.gradient_checkpointing:
            cmd.append("--gradient_checkpointing")
        
        return cmd
    
    def _build_simpletuner_config(self, config: TrainingConfig, dataset_dir: Path) -> dict:
        """构建 SimpleTuner 配置。"""
        return {
            "model_name": config.base_model,
            "data_dir": str(dataset_dir),
            "output_dir": str(config.output_dir),
            "resolution": config.resolution,
            "train_batch_size": config.batch_size,
            "gradient_accumulation_steps": config.gradient_accumulation,
            "max_train_steps": config.max_train_steps,
            "learning_rate": config.learning_rate,
            "lora_rank": config.network_dim,
            "lora_alpha": config.network_alpha,
            "mixed_precision": config.mixed_precision,
            "use_8bit_adam": config.optimizer == "adamw8bit",
            "gradient_checkpointing": config.gradient_checkpointing,
        }
    
    async def train(
        self,
        config: TrainingConfig,
        on_progress: Callable[[TrainingProgress], None] | None = None,
    ) -> TrainingResult:
        """执行 LoRA 训练。
        
        Args:
            config: 训练配置。
            on_progress: 进度回调函数。
            
        Returns:
            训练结果。
        """
        self._progress = TrainingProgress(
            total_steps=config.max_train_steps,
            status="running",
        )
        
        if on_progress:
            on_progress(self._progress)
        
        try:
            # 准备数据集
            dataset_dir = self._prepare_dataset(config)
            logger.info("数据集已准备: %s", dataset_dir)
            
            # 选择训练脚本
            if self._kohya_path and self._kohya_path.exists():
                cmd = self._build_kohya_command(config, dataset_dir)
                logger.info("使用 kohya_ss 训练")
            elif self._simpletuner_path and self._simpletuner_path.exists():
                # SimpleTuner 使用配置文件
                st_config = self._build_simpletuner_config(config, dataset_dir)
                config_file = dataset_dir / "config.json"
                with open(config_file, "w", encoding="utf-8") as f:
                    json.dump(st_config, f, indent=2)
                cmd = ["python", str(self._simpletuner_path / "train.py"), "--config", str(config_file)]
                logger.info("使用 SimpleTuner 训练")
            else:
                raise RuntimeError(
                    "未找到训练脚本，请配置 kohya_path 或 simpletuner_path"
                )
            
            # 执行训练
            logger.info("开始训练: %s", " ".join(cmd))
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            self._current_process = process
            
            # 读取输出并更新进度
            import re
            step_pattern = re.compile(r"step[:\s]+(\d+)")
            loss_pattern = re.compile(r"loss[:\s]+([\d.]+)")
            
            async for line in process.stdout:
                line_text = line.decode("utf-8", errors="replace").strip()
                logger.debug(line_text)
                
                # 解析进度
                step_match = step_pattern.search(line_text.lower())
                if step_match:
                    self._progress.current_step = int(step_match.group(1))
                
                loss_match = loss_pattern.search(line_text.lower())
                if loss_match:
                    self._progress.loss = float(loss_match.group(1))
                
                if on_progress:
                    on_progress(self._progress)
            
            await process.wait()
            
            if process.returncode != 0:
                raise RuntimeError(f"训练失败，退出码: {process.returncode}")
            
            # 查找输出的 LoRA 文件
            output_dir = Path(config.output_dir)
            lora_files = list(output_dir.glob("*.safetensors"))
            
            if not lora_files:
                raise RuntimeError("训练完成但未找到 LoRA 文件")
            
            lora_path = lora_files[0]
            
            self._progress.status = "completed"
            if on_progress:
                on_progress(self._progress)
            
            return TrainingResult(
                success=True,
                lora_path=lora_path,
                config=config,
                final_loss=self._progress.loss,
                metadata={
                    "vram_mode": "low" if self._is_low_vram_mode() else "standard",
                },
            )
            
        except Exception as e:
            logger.error("训练失败: %s", e)
            self._progress.status = "failed"
            self._progress.error = str(e)
            if on_progress:
                on_progress(self._progress)
            
            return TrainingResult(
                success=False,
                error=str(e),
                config=config,
            )
        
        finally:
            self._current_process = None
    
    def cancel(self) -> bool:
        """取消当前训练。"""
        if self._current_process:
            self._current_process.terminate()
            self._progress.status = "failed"
            self._progress.error = "用户取消"
            return True
        return False
    
    @property
    def progress(self) -> TrainingProgress:
        """当前训练进度。"""
        return self._progress
    
    def list_trained_models(self, models_dir: Path | str = "models/lora") -> list[dict]:
        """列出已训练的 LoRA 模型。
        
        Args:
            models_dir: 模型目录。
            
        Returns:
            模型列表。
        """
        models_dir = Path(models_dir)
        if not models_dir.exists():
            return []
        
        models = []
        for lora_file in models_dir.rglob("*.safetensors"):
            models.append({
                "name": lora_file.stem,
                "path": str(lora_file),
                "size_mb": lora_file.stat().st_size / (1024 * 1024),
                "character": lora_file.parent.name,
            })
        
        return models
