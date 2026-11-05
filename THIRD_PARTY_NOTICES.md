# THIRD_PARTY_NOTICES — VietDub Local

Danh mục dưới đây được sinh bởi `scripts/gen_notices.py` từ metadata gói đã cài. `UNKNOWN` nghĩa là metadata chưa đủ, không phải không có giấy phép. Cập nhật đóng gói 0.1.1: bản đầy đủ giấy phép của uv và các thư viện JavaScript đi kèm nằm trong `THIRD_PARTY_LICENSES/`. Các dependencies Python, llama/CUDA và trọng số model được tải riêng từ upstream khi người dùng đồng ý; không đóng các môi trường này vào ZIP.

Giấy phép PolyForm của VietDub chỉ áp dụng phần mã/tài liệu của dự án. Các thư viện và model bên thứ ba giữ nguyên giấy phép, quyền và điều khoản của chủ sở hữu tương ứng. Không áp hạn chế phi thương mại của VietDub lên mã bên thứ ba được cấp phép riêng. Danh mục metadata không thay nội dung giấy phép upstream.

## Runtime và công cụ đi kèm

| Thành phần | Phiên bản | License | Nguồn |
|---|---|---|---|
| llama.cpp (llama-server, CUDA build) | b11126 (commit b1ff4ca23) CUDA 13.4 x64 | MIT | https://github.com/ggml-org/llama.cpp |
| NVIDIA CUDA runtime (cudart/cublas, kèm bản llama.cpp) | 13.4 | NVIDIA CUDA Toolkit EULA (redistributable) | https://docs.nvidia.com/cuda/eula/ |
| CPython (uv-managed, python-build-standalone) | 3.11.16 | PSF-2.0 | https://www.python.org/ |
| uv | 0.12.18 | MIT OR Apache-2.0 | https://github.com/astral-sh/uv |

## Mô hình (tải theo đồng ý của người dùng, không đóng kèm gói)

| Model ID | Repo | Revision | License (theo model card) |
|---|---|---|---|
| qwen35_4b_q5 | unsloth/Qwen3.5-4B-GGUF | `e87f176479d0` | apache-2.0 |
| qwen35_4b_q4 | unsloth/Qwen3.5-4B-GGUF | `e87f176479d0` | apache-2.0 |
| gemma4_e4b_qat | google/gemma-4-E4B-it-qat-q4_0-gguf | `4b4a2c1d584b` | apache-2.0 |
| gemma4_e2b_qat | google/gemma-4-E2B-it-qat-q4_0-gguf | `675cff42a74c` | apache-2.0 |
| whisper_small_en | Systran/faster-whisper-small.en | `d1d751a5f827` | mit |
| vieneu_v3_turbo | pnnbao-ump/VieNeu-TTS-v3-Turbo | `61b85e3d937f` | apache-2.0 |
| moss_audio_tokenizer_nano | OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano | `6aa02b01e445` | apache-2.0 |

Người dùng tự chịu trách nhiệm tuân thủ điều khoản model card khi sử dụng. VieNeu v3 Turbo đi kèm watermark âm thanh khi SDK hỗ trợ.

## Python — broker/companion (`requirements/broker.lock.txt`)

| Gói | Phiên bản | License |
|---|---|---|
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| attrs | 26.1.0 | MIT |
| certifi | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) |
| click | 8.5.0 | BSD-3-Clause |
| fastapi | 0.141.1 | MIT |
| h11 | 0.16.0 | MIT License |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD License |
| idna | 3.20 | BSD-3-Clause |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| numpy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| pillow | 12.3.0 | MIT-CMU |
| psutil | 7.2.2 | BSD-3-Clause |
| pydantic | 2.13.5 | MIT |
| pydantic_core | 2.46.5 | MIT |
| pystray | 0.19.5 | GNU Lesser General Public License v3 (LGPLv3) |
| PyYAML | 6.0.3 | MIT License |
| referencing | 0.37.0 | MIT |
| rpds-py | 2026.6.3 | MIT |
| six | 1.17.0 | MIT License |
| starlette | 1.7.0 | BSD-3-Clause |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| uvicorn | 0.53.0 | BSD-3-Clause |
| websockets | 17.1 | BSD-3-Clause |

## Python — môi trường giọng đọc VieNeu (`requirements/tts.lock.txt`)

| Gói | Phiên bản | License |
|---|---|---|
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| audioread | 3.1.0 | MIT |
| brotli | 1.2.0 | MIT |
| certifi | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) |
| cffi | 2.1.1 | MIT-0 |
| charset-normalizer | 3.5.1 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| cloudpickle | 3.1.2 | BSD License |
| colorama | 0.4.6 | BSD License |
| decorator | 5.3.1 | BSD-2-Clause |
| fastapi | 0.141.1 | MIT |
| filelock | 3.32.3 | MIT |
| flatbuffers | 25.12.19 | Apache Software License |
| fsspec | 2026.7.0 | BSD-3-Clause |
| gradio | 6.17.3 | Apache-2.0 |
| gradio_client | 2.5.0 | Apache-2.0 |
| groovy | 0.1.2 | MIT License |
| h11 | 0.16.0 | MIT License |
| hf-gradio | 0.4.1 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD License |
| huggingface_hub | 0.36.2 | Apache Software License |
| idna | 3.20 | BSD-3-Clause |
| Jinja2 | 3.1.6 | BSD License |
| joblib | 1.6.0 | BSD-3-Clause |
| kaldi-native-fbank | 1.22.3 | Apache-2.0 |
| lazy-loader | 0.6 | BSD-3-Clause |
| librosa | 0.11.0 | ISC License (ISCL) |
| llvmlite | 0.49.0 | UNKNOWN |
| markdown-it-py | 4.2.0 | MIT License |
| MarkupSafe | 3.0.3 | BSD-3-Clause |
| mdurl | 0.1.2 | MIT License |
| mpmath | 1.3.0 | BSD License |
| msgpack | 1.2.2 | Apache-2.0 |
| narwhals | 2.26.0 | MIT |
| networkx | 3.6.1 | BSD-3-Clause |
| numba | 0.67.0 | BSD License |
| numpy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| onnxruntime | 1.30.0 | MIT License |
| orjson | 3.12.0 | MPL-2.0 AND (Apache-2.0 OR MIT) |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pandas | 3.0.6 | BSD License |
| pillow | 12.3.0 | MIT-CMU |
| platformdirs | 4.11.12 | MIT |
| pooch | 1.9.0 | BSD-3-Clause |
| protobuf | 7.36.2 | 3-Clause BSD License |
| pycparser | 3.0 | BSD-3-Clause |
| pydantic | 2.13.5 | MIT |
| pydantic_core | 2.46.5 | MIT |
| pydub | 0.25.1 | MIT License |
| Pygments | 2.21.0 | BSD-2-Clause |
| python-dateutil | 2.9.0.post0 | Apache Software License; BSD License |
| python-multipart | 0.0.32 | Apache-2.0 |
| pytz | 2026.3.post1 | MIT License |
| PyYAML | 6.0.3 | MIT License |
| regex | 2026.9.10 | Apache-2.0 AND CNRI-Python |
| requests | 2.34.2 | Apache Software License |
| rich | 15.0.0 | MIT License |
| safehttpx | 0.1.7 | MIT License |
| safetensors | 0.8.0 | Apache Software License |
| scikit-learn | 1.9.1 | BSD-3-Clause |
| scipy | 1.17.1 | BSD License |
| sea-g2p | 0.10.0 | Apache Software License |
| semantic-version | 2.10.0 | BSD License |
| shellingham | 1.5.4 | ISC License (ISCL) |
| six | 1.17.0 | MIT License |
| soundfile | 0.14.0 | BSD License |
| soxr | 1.1.0 | LGPL-2.1-or-later |
| starlette | 1.6.0 | BSD-3-Clause |
| sympy | 1.14.0 | BSD License |
| threadpoolctl | 3.7.0 | BSD-3-Clause |
| tokenizers | 0.22.2 | Apache Software License |
| tomlkit | 0.14.0 | MIT License |
| torch | 2.8.0+cu128 | BSD License |
| torchaudio | 2.8.0+cu128 | BSD License |
| tqdm | 4.70.1 | MPL-2.0 AND MIT |
| transformers | 4.57.6 | Apache Software License |
| typer | 0.27.2 | MIT |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| tzdata | 2026.4 | Apache-2.0 |
| urllib3 | 2.8.0 | MIT |
| uvicorn | 0.53.0 | BSD-3-Clause |
| vieneu | 3.8.1 | Apache Software License |

## Python — môi trường nhận dạng giọng nói (`requirements/asr.lock.txt`)

| Gói | Phiên bản | License |
|---|---|---|
| anyio | 4.15.1 | MIT |
| av | 18.1.0 | BSD-3-Clause |
| brotli | 1.2.0 | MIT |
| certifi | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) |
| charset-normalizer | 3.5.1 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| colorama | 0.4.6 | BSD License |
| ctranslate2 | 4.8.2 | MIT |
| faster-whisper | 1.2.1 | MIT License |
| feedparser-sgmllib | 2.1.0 | PSF-2.0 |
| filelock | 4.0.1 | MIT |
| flatbuffers | 25.12.19 | Apache Software License |
| fsspec | 2026.9.0 | BSD-3-Clause |
| h11 | 0.16.0 | MIT License |
| hf-xet | 1.6.0 | Apache-2.0 |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD License |
| huggingface_hub | 1.32.0 | Apache Software License |
| idna | 3.20 | BSD-3-Clause |
| mutagen | 1.48.1 | GPL-2.0-or-later |
| numpy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| nvidia-cublas-cu12 | 12.9.2.10 | LicenseRef-NVIDIA-Proprietary |
| nvidia-cuda-nvrtc-cu12 | 12.9.86 | Other/Proprietary License |
| nvidia-cudnn-cu12 | 9.26.0.51 | LicenseRef-NVIDIA-Proprietary |
| onnxruntime | 1.30.0 | MIT License |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| protobuf | 7.36.2 | 3-Clause BSD License |
| pycryptodomex | 3.23.0 | BSD License; Public Domain |
| PyYAML | 6.0.3 | MIT License |
| requests | 2.34.2 | Apache Software License |
| tokenizers | 0.23.2 | Apache Software License |
| tqdm | 4.70.1 | MPL-2.0 AND MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| urllib3 | 2.8.0 | MIT |
| websockets | 17.1 | BSD-3-Clause |
| yt-dlp-ejs | 0.8.0 | Unlicense AND MIT AND ISC |

## JavaScript đóng gói trong extension

| Gói | Phiên bản | License |
|---|---|---|
| react | 19.3.0 | MIT |
| react-dom | 19.3.0 | MIT |
| scheduler | 0.28.0 | MIT |
| zod | 4.6.5 | MIT |

Tổng: 154 gói; 1 gói không khai báo license trong metadata.
