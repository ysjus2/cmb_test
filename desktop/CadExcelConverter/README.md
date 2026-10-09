# CMB DXF Viewer + Excel v3.36

이 폴더가 현재 PC 실행본의 소스 기준입니다. 동작 설명은 [CURRENT_BEHAVIOR.md](../../CURRENT_BEHAVIOR.md), 서버 연동 준비 사항은 [SERVER_INTEGRATION.md](../../SERVER_INTEGRATION.md)를 읽으세요.

직접 `main.py`를 실행·빌드합니다. 별도 패치 적용 단계는 없습니다.

Windows/Python 3.12에서:

```powershell
python -m pip install --no-deps ezdxf==1.0.3 pyproj==3.7.2
python -m pip install -r requirements.txt
python run_checks.py
python -m PyInstaller --noconfirm --clean --onefile --windowed --name CMB_DXF_Viewer_v3.36 --collect-all pyproj --collect-all ezdxf --exclude-module numpy --exclude-module fontTools main.py
```

네트워크 CA 패키지 대신 원본 프로젝트의 `certifi.py` 로컬 호환 모듈을 사용합니다. 일반 pip 자동 의존성 설치로 실행본의 의존성을 바꾸지 마세요. 이 실행본의 런타임 기준은 ezdxf 1.0.3, openpyxl 3.1.5, pyproj 3.7.2입니다. PyInstaller는 빌드 도구입니다.

실행 파일과 서드파티 고지는 [pc-releases/current](../../pc-releases/current)에 있습니다. 원본 DXF와 실제 캐시는 배포에 포함하지 않습니다.
