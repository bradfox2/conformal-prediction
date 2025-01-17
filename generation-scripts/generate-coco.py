import os
import shutil
import sys
from pathlib import Path

import numpy as np
import torch
import torchvision.transforms as transforms
from tqdm import tqdm

sys.path.insert(1, os.path.join(sys.path[0], "./coco_utils"))

from coco_utils.custom_coco_dataloader import CocoDetectionWithPaths
from coco_utils.ml_decoder.helper_functions.bn_fusion import fuse_bn_recursively
from coco_utils.ml_decoder.models import create_model
from coco_utils.ml_decoder.models.tresnet.tresnet import InplacABN_to_ABN

ABSPATH = Path(__file__).parent.absolute()

# Computes scores and targets from a model and loader
def get_scores_targets(model, loader):
    scores = torch.zeros((len(loader.dataset), 80))
    labels = torch.zeros((len(loader.dataset), 80))
    paths = []
    i = 0
    print("Computing sigmoid scores for model (only happens once).")
    with torch.no_grad():
        for x, batch_labels, path in tqdm(loader):
            paths += list(path)

            batch_scores = torch.sigmoid(model(x.cuda())).detach().cpu()
            scores[i : (i + x.shape[0]), :] = batch_scores

            labels[i : (i + x.shape[0]), :] = batch_labels
            i = i + x.shape[0]

    keep = labels.sum(dim=1) > 0
    scores = scores[keep].numpy()
    labels = labels[keep].numpy()
    paths = np.array(paths)[keep.numpy()]

    return scores, labels, paths


if __name__ == "__main__":
    with torch.no_grad():
        args = {
            "num_classes": 80,
            "model_path": str(ABSPATH) + "/coco_utils/tresnet_xl_COCO_640_91_4.pth",
            "model_name": "tresnet_xl",
            "input_size": 640,
            "use_ml_decoder": 1,
        }

        # Setup model
        print(f'creating model {args["model_name"]}...')
        if not os.path.exists(args["model_path"]):
            os.system(
                "wget https://miil-public-eu.oss-eu-central-1.aliyuncs.com/model-zoo/ML_Decoder/tresnet_xl_COCO_640_91_4.pth -O "
                + args["model_path"]
            )
        model = create_model(args, load_head=True).cuda()
        model = model.cpu()
        model = InplacABN_to_ABN(model)
        model = fuse_bn_recursively(model)
        model = model.cuda().eval()
        state = torch.load(args["model_path"], map_location="cpu")
        classes_list = np.array(list(state["idx_to_class"].values()))
        os.makedirs(f"{str(ABSPATH.parent)}/data/coco/", exist_ok=True)
        np.save(
            f"{str(ABSPATH.parent)}/data/coco/human_readable_labels.npy", classes_list
        )

        args["num_classes"] = state["num_classes"]
        model.eval()

        print("Model Loaded")
        # corr = get_correspondence(classes_list,coco_dataset.coco.cats)

        COCO_VAL_2017_DIRECTORY = (
            "/home/aa/Code/conformal-risk-control/coco/data/val2017"
        )
        COCO_INSTANCES_VAL_2017_JSON = "/home/aa/Code/conformal-risk-control/coco/data/annotations_trainval2017/instances_val2017.json"
        coco_dataset = CocoDetectionWithPaths(
            COCO_VAL_2017_DIRECTORY,
            COCO_INSTANCES_VAL_2017_JSON,
            classes_list,
            transform=transforms.Compose(
                [
                    transforms.Resize((args["input_size"], args["input_size"])),
                    transforms.ToTensor(),
                ]
            ),
        )
        print("Dataset loaded")

        coco_dataloader = torch.utils.data.DataLoader(
            coco_dataset, batch_size=128, shuffle=False
        )

        scores, labels, paths = get_scores_targets(model, coco_dataloader)

        example_indexes = np.random.choice(
            paths.shape[0], size=(500,), replace=False, p=None
        )  # Randomly sample 500 images for people to play with

        print("saving the scores and labels")
        os.makedirs(f"{str(ABSPATH.parent)}/data/coco/examples", exist_ok=True)
        np.savez(
            f"{str(ABSPATH.parent)}/data/coco/coco-tresnetxl.npz",
            sgmd=scores,
            labels=labels,
            example_indexes=example_indexes,
        )

        print("moving a subset of images to the examples folder")
        for idx in example_indexes:
            shutil.copy(
                f"{COCO_VAL_2017_DIRECTORY}/{paths[idx]}",
                f"{str(ABSPATH.parent)}/data/coco/examples/{str(idx)}.jpg",
            )
