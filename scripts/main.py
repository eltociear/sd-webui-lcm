from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import uuid
from lcm.lcm_scheduler import LCMScheduler
from lcm.lcm_pipeline import LatentConsistencyModelPipeline
import modules.scripts as scripts
from modules import script_callbacks
import os
import random
import time
import numpy as np
import gradio as gr
from PIL import Image, PngImagePlugin
import torch


DESCRIPTION = '''# Latent Consistency Model
Running [LCM_Dreamshaper_v7](https://huggingface.co/SimianLuo/LCM_Dreamshaper_v7) | [Project Page](https://latent-consistency-models.github.io) | [Extension Page](https://github.com/0xbitches/sd-webui-lcm)
'''

MAX_SEED = np.iinfo(np.int32).max
MAX_IMAGE_SIZE = int(os.getenv("MAX_IMAGE_SIZE", "768"))


class Script(scripts.Script):
    def __init__(self) -> None:
        super().__init__()

    def title(self):
        return "LCM"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        return ()


def randomize_seed_fn(seed: int, randomize_seed: bool) -> int:
    if randomize_seed:
        seed = random.randint(0, MAX_SEED)
    return seed


def save_image(img, metadata: dict):
    save_dir = os.path.join(scripts.basedir(), "outputs/txt2img-images/LCM/")
    Path(save_dir).mkdir(exist_ok=True, parents=True)
    seed = metadata["seed"]
    unique_id = uuid.uuid4()
    filename = save_dir + f"{unique_id}-{seed}" + ".png"

    meta_tuples = [(k, str(v)) for k, v in metadata.items()]
    png_info = PngImagePlugin.PngInfo()
    for k, v in meta_tuples:
        png_info.add_text(k, v)
    img.save(filename, pnginfo=png_info)

    return filename


def save_images(image_array, metadata: dict):
    paths = []
    with ThreadPoolExecutor() as executor:
        paths = list(executor.map(save_image, image_array,
                     [metadata]*len(image_array)))
    return paths


scheduler = LCMScheduler.from_pretrained(
    "SimianLuo/LCM_Dreamshaper_v7", subfolder="scheduler")
pipe = LatentConsistencyModelPipeline.from_pretrained(
    "SimianLuo/LCM_Dreamshaper_v7", scheduler=scheduler)
pipe.safety_checker = None  # ¯\_(ツ)_/¯


def generate(
    prompt: str,
    seed: int = 0,
    width: int = 512,
    height: int = 512,
    guidance_scale: float = 8.0,
    num_inference_steps: int = 4,
    num_images: int = 4,
    randomize_seed: bool = False,
    use_fp16: bool = True,
    use_torch_compile: bool = False,
    progress=gr.Progress(track_tqdm=True)
) -> Image.Image:
    seed = randomize_seed_fn(seed, randomize_seed)
    torch.manual_seed(seed)

    if use_fp16:
        pipe.to(torch_device="cuda", torch_dtype=torch.float16)
    else:
        pipe.to(torch_device="cuda", torch_dtype=torch.float32)

    # Windows does not support torch.compile for now
    if os.name != 'nt' and use_torch_compile:
        pipe.unet = torch.compile(pipe.unet, mode='max-autotune')

    start_time = time.time()
    result = pipe(
        prompt=prompt,
        width=width,
        height=height,
        guidance_scale=guidance_scale,
        num_inference_steps=num_inference_steps,
        num_images_per_prompt=num_images,
        lcm_origin_steps=50,
        output_type="pil",
    ).images
    paths = save_images(result, metadata={"prompt": prompt, "seed": seed, "width": width,
                        "height": height, "guidance_scale": guidance_scale, "num_inference_steps": num_inference_steps})

    elapsed_time = time.time() - start_time
    print("LCM inference time: ", elapsed_time, "seconds")
    return paths, seed


examples = [
    "portrait photo of a girl, photograph, highly detailed face, depth of field, moody light, golden hour, style by Dan Winters, Russell James, Steve McCurry, centered, extremely detailed, Nikon D850, award winning photography",
    "Self-portrait oil painting, a beautiful cyborg with golden hair, 8k",
    "Astronaut in a jungle, cold color palette, muted colors, detailed, 8k",
    "A photo of beautiful mountain with realistic sunset and blue lake, highly detailed, masterpiece",
]


def on_ui_tabs():
    with gr.Blocks(css="style.css") as lcm:
        gr.Markdown(DESCRIPTION)
        with gr.Group():
            with gr.Row():
                prompt = gr.Text(
                    label="Prompt",
                    show_label=False,
                    max_lines=1,
                    placeholder="Enter your prompt",
                    container=False,
                )
                run_button = gr.Button("Run", scale=0)
            result = gr.Gallery(
                label="Generated images", show_label=False, elem_id="gallery", grid=[2], preview=True
            )
        with gr.Accordion("Advanced options", open=False):
            seed = gr.Slider(
                label="Seed",
                minimum=0,
                maximum=MAX_SEED,
                step=1,
                value=0,
                randomize=True
            )
            randomize_seed = gr.Checkbox(
                label="Randomize seed across runs", value=True)
            use_fp16 = gr.Checkbox(
                label="Run LCM in fp16 (for lower VRAM)", value=True)
            use_torch_compile = gr.Checkbox(
                label="Run LCM with torch.compile (currently not supported on Windows)", value=False)
            with gr.Row():
                width = gr.Slider(
                    label="Width",
                    minimum=256,
                    maximum=MAX_IMAGE_SIZE,
                    step=32,
                    value=512,
                )
                height = gr.Slider(
                    label="Height",
                    minimum=256,
                    maximum=MAX_IMAGE_SIZE,
                    step=32,
                    value=512,
                )
            with gr.Row():
                guidance_scale = gr.Slider(
                    label="Guidance scale for base",
                    minimum=2,
                    maximum=14,
                    step=0.1,
                    value=8.0,
                )
                num_inference_steps = gr.Slider(
                    label="Number of inference steps for base",
                    minimum=1,
                    maximum=8,
                    step=1,
                    value=4,
                )
            with gr.Row():
                num_images = gr.Slider(
                    label="Number of images (batch count)",
                    minimum=1,
                    maximum=100,
                    step=1,
                    value=4,
                )

        gr.Examples(
            examples=examples,
            inputs=prompt,
            outputs=result,
            fn=generate
        )

        run_button.click(
            fn=generate,
            inputs=[
                prompt,
                seed,
                width,
                height,
                guidance_scale,
                num_inference_steps,
                num_images,
                randomize_seed,
                use_fp16,
                use_torch_compile
            ],
            outputs=[result, seed],
        )
    return [(lcm, "LCM", "lcm")]


script_callbacks.on_ui_tabs(on_ui_tabs)
