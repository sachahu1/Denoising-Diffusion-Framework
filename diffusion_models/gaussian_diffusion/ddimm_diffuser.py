from enum import Enum
from typing import List
from typing import Tuple

import numpy as np
import torch
from tqdm import tqdm

from diffusion_models.gaussian_diffusion.base_diffuser import BaseDiffuser
from diffusion_models.gaussian_diffusion.beta_schedulers import (
  BaseBetaScheduler,
)
from diffusion_models.models.base_diffusion_model import BaseDiffusionModel
from diffusion_models.utils.schemas import Checkpoint, Timestep


class DenoisingMode(str, Enum):
  Linear = "linear"
  Quadratic = "quadratic"


class DdimDiffuser(BaseDiffuser):
  def __init__(
    self,
    beta_scheduler: BaseBetaScheduler,
    mode: DenoisingMode = DenoisingMode.Quadratic,
    number_of_steps: int = 20,
  ):
    """Initializes the class instance.

    Args:
      beta_scheduler (BaseBetaScheduler): The beta scheduler instance to be used.

    """
    super().__init__(beta_scheduler)

    self.number_of_steps = number_of_steps
    """Number of steps to use in the denoising process."""

    self.mode = mode
    """Linear or Quadratic sampling."""

    self.device: str = "cpu"
    """The device to use. Defaults to cpu."""

  @property
  def steps(self) -> List[int]:
    if self.mode == DenoisingMode.Linear:
      a = self.beta_scheduler.steps // self.number_of_steps
      time_steps = np.asarray(list(range(0, self.beta_scheduler.steps, a)))
    else:
      time_steps = (
        np.linspace(
          0, np.sqrt(self.beta_scheduler.steps * 0.8), self.number_of_steps
        )
        ** 2
      ).astype(int)
    self._time_steps = time_steps + 1
    self._time_steps_prev = np.concatenate([[0], time_steps[:-1]])
    return list(range(self.number_of_steps))[::-1]

  def get_timestep(self, number_of_images: int, idx: int) -> Timestep:
    timestep = torch.full(
      (number_of_images,), self._time_steps[idx], device=self.device
    )
    timestep_prev = torch.full(
      (number_of_images,), self._time_steps_prev[idx], device=self.device
    )
    return Timestep(
      current=timestep,
      previous=timestep_prev,
    )

  @classmethod
  def from_checkpoint(cls, checkpoint: Checkpoint) -> "DdimDiffuser":
    """Instantiate a DDIM Diffuser from a training checkpoint.

    Args:
      checkpoint: The training checkpoint object containing
        the trained model's parameters and configuration.

    Returns:
      An instance of the DdimDiffuser class initialized with the parameters
      loaded from the given checkpoint.
    """
    return cls(
      beta_scheduler=BaseBetaScheduler.from_tensors(
        steps=checkpoint.beta_scheduler_config.steps,
        betas=checkpoint.beta_scheduler_config.betas,
        alpha_bars=checkpoint.beta_scheduler_config.alpha_bars,
      )
    )

  def to(self, device: str = "cpu"):
    """Moves the data to the specified device.

    This performs a similar behaviour to the `to` method of PyTorch. moving the
    GaussianDiffuser and the BetaScheduler to the specified device.

    Args:
      device: The device to which the method should move the object.
        Default is "cpu".

    Example:
      >>> ddim_diffuser = DdimDiffuser()
      >>> ddim_diffuser = ddim_diffuser.to(device="cuda")
    """
    self.device = device
    self.beta_scheduler = self.beta_scheduler.to(self.device)
    return self

  def _diffuse_batch(
    self, images: torch.Tensor, timesteps: torch.Tensor
  ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    noise = torch.randn_like(images, device=self.device)

    alpha_bar_t = self.beta_scheduler.alpha_bars.gather(dim=0, index=timesteps)

    alpha_bar_t = alpha_bar_t.reshape((-1, *((1,) * (len(images.shape) - 1))))

    mu = torch.sqrt(alpha_bar_t)
    sigma = torch.sqrt(1 - alpha_bar_t)
    images = mu * images + sigma * noise
    return images, noise, timesteps

  def diffuse_batch(
    self, images: torch.Tensor
  ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Diffuse a batch of images.

    Diffuse the given batch of images by adding noise based on the beta scheduler.

    Args:
      images: Batch of images to diffuse.\n
        Shape should be ``(B, C, H, W)``.

    Returns:
      A tuple containing three tensors

        - images: Diffused batch of images.
        - noise: Noise added to the images.
        - timesteps: Timesteps used for diffusion.
    """
    timesteps = torch.randint(
      0, self.beta_scheduler.steps, (images.shape[0],), device=self.device
    )
    return self._diffuse_batch(images, timesteps)

  @torch.no_grad()
  def _denoise_step(
    self,
    images: torch.Tensor,
    model: torch.nn.Module,
    timestep: Timestep,
    eta: float = 0.0,
  ) -> torch.Tensor:
    current_timestep = timestep.current
    previous_timestep = timestep.previous

    epsilon_theta = model(images, current_timestep)

    alpha_bar_t = self.beta_scheduler.alpha_bars.gather(
      dim=0, index=current_timestep
    ).reshape(-1, 1, 1, 1)

    alpha_bar_t_prev = self.beta_scheduler.alpha_bars.gather(
      dim=0, index=previous_timestep
    ).reshape(-1, 1, 1, 1)

    sigma = eta * torch.sqrt(
      (1 - alpha_bar_t_prev)
      / (1 - alpha_bar_t)
      * (1 - alpha_bar_t / alpha_bar_t_prev)
    )

    epsilon_t = torch.randn_like(images)

    mu = (
      torch.sqrt(alpha_bar_t_prev / alpha_bar_t) * images
      + (
        torch.sqrt(1 - alpha_bar_t_prev - sigma**2)
        - torch.sqrt((alpha_bar_t_prev * (1 - alpha_bar_t)) / alpha_bar_t)
      )
      * epsilon_theta
    )
    return mu + sigma * epsilon_t

  def denoise_batch(
    self,
    images: torch.Tensor,
    model: "BaseDiffusionModel",
  ) -> List[torch.Tensor]:
    """Denoise a batch of images.

    This denoises a batch images. This is the image generation process.

    Args:
      images: A batch of noisy images.
      model: The model to be used for denoising.

    Returns:
      A list of tensors containing a batch of denoised images.
    """
    denoised_images = []
    for i in tqdm(self.steps, desc="Denoising"):
      timestep = self.get_timestep(images.shape[0], idx=i)

      images = self._denoise_step(
        images,
        model=model,
        timestep=timestep,
      )
      images = torch.clamp(images, -1.0, 1.0)
      denoised_images.append(images)
    return denoised_images
