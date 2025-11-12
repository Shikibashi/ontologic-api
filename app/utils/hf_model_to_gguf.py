import subprocess
import shutil
import os

import sys
from pathlib import Path

from app.core.logger import log

from transformers import AutoModel, AutoTokenizer, AutoConfig

class HfModelToGGUF():

    def __init__(self, model_name="ibm-granite/granite-embedding-125m-english"):
        
        self.base_dir = Path(__file__).resolve().parent.parent

        self.model_name = model_name
        self.local_dir = str(self.base_dir) + "/models/embedding"

    def download_hf_model(self):
        save_dir = self.local_dir + "/" + self.model_name.split('/')[-1]
        model = AutoModel.from_pretrained(self.model_name)
        tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        config = AutoConfig.from_pretrained(self.model_name)
        model.save_pretrained(save_dir)
        tokenizer.save_pretrained(save_dir)
        config.save_pretrained(save_dir)


    def convert_and_install_hf_to_gguf(self):
            model_name = self.model_name.split('/')[-1]
            outfile = f"{self.local_dir}/{model_name}.gguf"
            subprocess.run([
                "python", f"{str(self.base_dir.parent)}/llama.cpp/convert_hf_to_gguf.py",
                f"{self.local_dir}/{model_name}",
                "--outfile", outfile
            ], check=True)

            modelfile_path = f"{self.local_dir}/{model_name}_MODEL_FILE"
            with open(modelfile_path, "w") as modelfile:
                modelfile.write(f"FROM {outfile}\n")
            
            # Use ollama to create the model
            model_name = self.model_name.split('/')[-1]
            subprocess.run([
                "ollama", "create", model_name, "-f", modelfile_path
            ], check=True)

            log.info(f"Model {model_name} successfully registered with Ollama.")
