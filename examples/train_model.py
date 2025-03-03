"""Running a simple training script.

Below is a simple example of a training script. It contains basic configurations
for a simple diffusion model and constitutes a good starting point.

.. literalinclude:: /../../examples/train_model.py
   :language: python
   :linenos:
   :lines: 14-102
"""

__all__ = []

from torch.nn import functional as F
from torch.optim import AdamW
from torchvision import datasets
from torchvision.transforms import v2

from diffusion_models.diffusion_trainer import DiffusionTrainer
from diffusion_models.gaussian_diffusion.beta_schedulers import (
  LinearBetaScheduler,
)
from diffusion_models.gaussian_diffusion.gaussian_diffuser import (
  GaussianDiffuser,
)
from diffusion_models.models.SimpleUnet import SimpleUnet
from diffusion_models.utils.schemas import LogConfiguration
from diffusion_models.utils.schemas import TrainingConfiguration


if __name__ == "__main__":
  image_size = 64
  image_channels = 3

  training_configuration = TrainingConfiguration(
    batch_size=256,
    learning_rate=2 * 10e-4,
    number_of_epochs=500,
    training_name="ReworkedFrameworkBase",
    checkpoint_rate=100,
    mixed_precision_training=False,
    # gradient_clip=0.1,
  )
  log_configuration = LogConfiguration(
    log_rate=10,
    image_rate=635,
    number_of_images=5,
  )
  model = SimpleUnet(
    image_channels=image_channels,
    diffuser=GaussianDiffuser(
      beta_scheduler=LinearBetaScheduler(
        beta_start=0.0001,
        beta_end=0.02,
        steps=1000,
      ),
    ),
  )

  print("Num params: ", sum(p.numel() for p in model.parameters()))
  # model = model.compile(fullgraph=True, mode="reduce-overhead")

  # Define Image Transforms and Reverse Transforms
  image_transforms = v2.Compose(
    [
      v2.ToImage(),
      v2.Resize((image_size, image_size)),
      v2.Lambda(lambda x: (x + 1) / 2),
    ]
  )

  reverse_transforms = v2.Compose(
    [v2.Lambda(lambda x: (x + 1) / 2), v2.Resize((128, 128))]
  )

  # Define Dataset
  dataset = datasets.CelebA(
    root="../data", download=False, transform=image_transforms, split="train"
  )
  # dataset = datasets.MNIST(
  #   transform=image_transforms,
  #   root="../data",
  #   download=True
  # )

  # Instantiate DiffusionTrainer
  trainer = DiffusionTrainer(
    model=model,
    dataset=dataset,
    optimizer=AdamW(
      model.parameters(), lr=training_configuration.learning_rate
    ),
    reverse_transforms=reverse_transforms,
    training_configuration=training_configuration,
    loss_function=F.l1_loss,
    scheduler=None,
    log_configuration=log_configuration,
    device="cuda",
  )

  # Launch training
  trainer.train()
