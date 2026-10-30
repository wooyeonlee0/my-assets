import getpass
import json
import subprocess
import sys
import urllib.request
import urllib.error
from credentials import set_credential

def main():
    print("=" * 65)
    print(" 🚀 GitHub 저장소 자동 생성 & GitHub Pages 원클릭 배포 도구")
    print("=" * 65)
    print("이 도구는 화면에 토큰을 노출하지 않고 안전하게 입력받아,")
    print("GitHub 저장소 생성 ➔ 코드 푸시 ➔ Pages 웹 배포까지 전자동으로 처리합니다.\n")

    # 1. 토큰 마스킹 입력 (화면에 아무 글자도 찍히지 않음)
    try:
        pat = getpass.getpass("1. GitHub Personal Access Token (PAT) 붙여넣기 (화면에 안 보임): ").strip()
    except Exception:
        pat = input("1. GitHub Personal Access Token (PAT) 입력: ").strip()

    if not pat:
        print("❌ 토큰이 입력되지 않았습니다. 취소합니다.")
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "Valiant-Portfolio-Deployer",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # 2. 사용자 계정 정보 확인
    print("\n🔍 GitHub 계정 확인 중...")
    try:
        req = urllib.request.Request("https://api.github.com/user", headers=headers)
        with urllib.request.urlopen(req) as resp:
            user_data = json.loads(resp.read().decode("utf-8"))
            username = user_data["login"]
            print(f"   -> GitHub 계정 인식 완료: @{username}")
    except Exception as e:
        print(f"❌ 토큰 인증 실패: {e}")
        print("   -> 토큰에 'repo' 권한이 있는지 확인해 주세요.")
        sys.exit(1)

    # 3. 저장소 이름
    repo_name = input("\n2. 생성할 저장소 이름 (엔터 치면 'valiant-portfolio'): ").strip() or "valiant-portfolio"

    # 4. GitHub 저장소 자동 생성 (Public: Pages 무료 지원)
    print(f"\n📦 GitHub에 '{repo_name}' 원격 저장소 생성 중...")
    create_payload = json.dumps({
        "name": repo_name,
        "description": "Valiant Portfolio - 서버리스 PWA 자산관리 대시보드",
        "private": False,
        "auto_init": False,
    }).encode("utf-8")

    repo_created = False
    try:
        req = urllib.request.Request("https://api.github.com/user/repos", data=create_payload, headers=headers, method="POST")
        with urllib.request.urlopen(req) as resp:
            print("   -> 원격 저장소 생성 완료!")
            repo_created = True
    except urllib.error.HTTPError as e:
        if e.code == 422:
            print(f"   -> 이미 '{repo_name}' 저장소가 존재합니다. 기존 저장소에 푸시를 진행합니다.")
        else:
            print(f"❌ 저장소 생성 오류 ({e.code}): {e.read().decode('utf-8')}")
            sys.exit(1)

    # 5. Git Remote 설정 및 Push
    remote_url = f"https://{username}:{pat}@github.com/{username}/{repo_name}.git"
    clean_remote_url = f"https://github.com/{username}/{repo_name}.git"

    print("\n📤 로컬 코드 푸시(Push) 진행 중...")
    try:
        subprocess.run(["git", "remote", "remove", "origin"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "remote", "add", "origin", remote_url], check=True)
        push_res = subprocess.run(["git", "push", "-u", "origin", "master", "--force"], check=True, capture_output=True, text=True)
        print("   -> master 브랜치 푸시 완료!")
    except subprocess.CalledProcessError as e:
        print(f"❌ 푸시 실패: {e.stderr}")
        sys.exit(1)
    finally:
        # 보안 조치: .git/config의 remote url에서 PAT 제거하고 깔끔한 URL로 재설정
        subprocess.run(["git", "remote", "set-url", "origin", clean_remote_url], check=False)

    # 6. GitHub Pages 자동 활성화
    print("\n🌐 GitHub Pages 자동 활성화 중...")
    pages_payload = json.dumps({
        "source": {
            "branch": "master",
            "path": "/"
        }
    }).encode("utf-8")

    pages_url = f"https://{username}.github.io/{repo_name}/"
    try:
        pages_req = urllib.request.Request(
            f"https://api.github.com/repos/{username}/{repo_name}/pages",
            data=pages_payload,
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(pages_req) as resp:
            print("   -> GitHub Pages가 성공적으로 활성화되었습니다!")
    except urllib.error.HTTPError as e:
        if e.code == 409:
            print("   -> GitHub Pages가 이미 켜져 있습니다.")
        else:
            print(f"   (참고: GitHub 설정에서 Pages가 빌드되는 중입니다: {e.code})")

    # 7. 토큰을 Windows 자격 증명 관리자에 안전하게 저장 (향후 동기화용)
    set_credential("GITHUB_PAT", pat)
    set_credential("GITHUB_REPO", f"{username}/{repo_name}")
    print("🔒 GitHub PAT 및 저장소 정보가 Windows 자격 증명 관리자(DPAPI)에 암호화 보관되었습니다.")

    print("\n" + "=" * 65)
    print(" 🎉 모든 배포가 성공적으로 완료되었습니다!")
    print("=" * 65)
    print(f"\n📱 폰에서 접속할 나만의 전용 인터넷 주소:")
    print(f"👉 {pages_url}\n")
    print("스마트폰 브라우저로 위 주소에 접속한 뒤 '홈 화면에 추가'를 누르면 끝납니다.")
    print("=" * 65)

if __name__ == "__main__":
    main()
