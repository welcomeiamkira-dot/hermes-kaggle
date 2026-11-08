import os, sys, subprocess, time, re, urllib.request

PASS = os.environ.get("HERMES_PASS")
if not PASS:
    sys.exit("HERMES_PASS set nahi hai (notebook ki pehli line dekho)")

REPO = "bartowski/NousResearch_Hermes-4.3-36B-GGUF"
FILE = "NousResearch_Hermes-4.3-36B-Q4_K_M.gguf"
MODEL = "/tmp/models/" + FILE
LLAMA = "/tmp/llama.cpp"
SERVER = LLAMA + "/build/bin/llama-server"


def sh(cmd):
    return subprocess.run(cmd, shell=True)


import glob, shutil
if subprocess.run("nvidia-smi -L", shell=True, capture_output=True).returncode != 0:
    sys.exit("GPU nahi mila: Settings > Accelerator > GPU T4 x2 chuno, phir cell dobara chalao")
NVCC = shutil.which("nvcc") or next(iter(sorted(glob.glob("/usr/local/cuda*/bin/nvcc"))), None)
if not NVCC:
    sys.exit("nvcc nahi mila (GPU image nahi hai?). Accelerator GPU T4 x2 rakho aur session restart karo")
CUDA_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(NVCC)))
os.environ["PATH"] = os.path.dirname(NVCC) + ":" + os.environ["PATH"]
os.environ["CUDACXX"] = NVCC
print("nvcc:", NVCC)


# 1) llama.cpp build (background mein, download ke saath saath)
build = None
if not os.path.exists(SERVER):
    cmd = (
        f"(test -d {LLAMA}/.git || (rm -rf {LLAMA}; git clone --depth 1 https://github.com/ggml-org/llama.cpp {LLAMA})) && cd {LLAMA} && "
        f"cmake -B build -DCMAKE_CUDA_COMPILER={NVCC} -DCUDAToolkit_ROOT={CUDA_ROOT} -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=75 -DLLAMA_CURL=OFF "
        "-DCUDA_cuda_driver_LIBRARY=/usr/local/nvidia/lib64/libcuda.so "
        "-DCMAKE_LIBRARY_PATH=/usr/local/nvidia/lib64 "
        "-DCMAKE_SHARED_LINKER_FLAGS=-L/usr/local/nvidia/lib64 "
        "-DCMAKE_EXE_LINKER_FLAGS=-L/usr/local/nvidia/lib64 "
        "&& cmake --build build --config Release -j 4 --target llama-server"
    )
    build = subprocess.Popen(cmd, shell=True, stdout=open("/tmp/build.log", "w"), stderr=subprocess.STDOUT)
    print("llama.cpp build shuru (10-15 min)...")

# 2) Model download
if not os.path.exists(MODEL):
    from huggingface_hub import hf_hub_download
    print("Model download shuru (5-10 min)...")
    hf_hub_download(REPO, FILE, local_dir="/tmp/models")
print("Model ready")

if build is not None:
    while build.poll() is None:
        time.sleep(30)
        try:
            last = open("/tmp/build.log").read().strip().splitlines()[-1]
        except Exception:
            last = ""
        print("build chal raha hai:", last[:90], flush=True)
    if not os.path.exists(SERVER):
        print(open("/tmp/build.log").read()[-1500:])
        sys.exit("Build fail hui, upar ka log bhejo")
print("Build ready")

# 3) Server
sh("pkill -9 -f llama-server; pkill -9 -f cloudflared; sleep 3")
srv = subprocess.Popen(
    [SERVER, "-m", MODEL, "-ngl", "99", "-ts", "1,1", "-c", "65536", "-fa", "on",
     "-ctk", "q4_0", "-ctv", "q4_0", "-b", "512", "-ub", "256",
     "--host", "127.0.0.1", "--port", "8080", "--api-key", PASS],
    stdout=open("/tmp/server.log", "w"), stderr=subprocess.STDOUT)
for i in range(60):
    time.sleep(5)
    try:
        print(urllib.request.urlopen("http://127.0.0.1:8080/health").read())
        break
    except Exception:
        pass
else:
    print(open("/tmp/server.log").read()[-1500:])
    sys.exit("Server nahi chala")

# 4) Link
if not os.path.exists("/tmp/cloudflared"):
    sh("wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O /tmp/cloudflared && chmod +x /tmp/cloudflared")
tun = subprocess.Popen(["/tmp/cloudflared", "tunnel", "--url", "http://127.0.0.1:8080"],
                       stdout=open("/tmp/tun.log", "w"), stderr=subprocess.STDOUT)
for i in range(20):
    time.sleep(3)
    m = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", open("/tmp/tun.log").read())
    if m:
        print("LINK:", m[0])
        break
