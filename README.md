# KBI 데이터 자동 갱신 (GitHub Actions)

이 저장소는 매일 자동으로 축산물품질평가원 API를 호출해서 KBI(Korea Barbecue Index)용 소비자가격 데이터를 갱신한다. 브라우저에서 직접 호출하면 CORS(다른 도메인 요청 차단)에 막히기 때문에, GitHub의 서버가 대신 호출하도록 만든 구조다.

## 설정 방법 (최초 1회만 하면 된다)

### 1. GitHub 저장소 만들기
1. github.com에 로그인한다 (계정 없으면 무료로 가입).
2. 우측 상단 **+** → **New repository** 클릭.
3. 이름은 아무거나 (예: `kbi-data`). **Public**으로 만들어도 되고 **Private**으로 만들어도 된다 (Private이 더 안전하다).
4. **Create repository** 클릭.

### 2. 이 폴더의 파일들을 저장소에 올리기
아래 파일 구조 그대로, 이 저장소에 업로드한다.

```
.github/workflows/update-kbi-data.yml
scripts/fetch-kbi-data.js
```

GitHub 웹 화면에서 **Add file → Upload files**로 드래그해서 올리면 된다 (git 명령어를 몰라도 된다).

### 3. 인증키를 Secret으로 등록하기 (중요 — 절대 코드에 직접 쓰지 않는다)
1. 저장소 페이지 상단 **Settings** 탭 클릭
2. 왼쪽 메뉴에서 **Secrets and variables → Actions** 클릭
3. **New repository secret** 클릭
4. Name: `EKAPE_SERVICE_KEY`
5. Value: 발급받은 인증키(59676a78e6f44b90da6102f357ce10ae81350d688bf7ce47a1a910118ccd653c) 붙여넣기
6. **Add secret** 클릭

### 4. 첫 실행 테스트
1. 저장소 상단 **Actions** 탭 클릭
2. 왼쪽에서 **Update KBI livestock price data** 워크플로 클릭
3. 우측 **Run workflow** 버튼 클릭 → 즉시 1회 실행됨
4. 몇 분 후 저장소에 `data/kbi-prices.json` 파일이 새로 생겼는지 확인

### 5. 이후로는?
아무것도 안 해도 된다. 매일 자동으로 실행되어 `data/kbi-prices.json`이 그날 시세로 갱신된다.

## KBI 웹페이지에서 이 데이터를 불러오는 방법

저장소가 **Public**이면, 아래 주소로 아무 웹페이지에서나 fetch 가능하다 (CORS 허용됨):

```
https://raw.githubusercontent.com/{깃허브아이디}/{저장소이름}/main/data/kbi-prices.json
```

이 주소를 KBI GlobalMap 페이지의 fetch 코드에 넣어주면, 페이지를 열 때마다 최신 데이터를 자동으로 불러온다.

(저장소를 Private으로 만들었다면 이 방식이 안 되니, 그 경우엔 알려주면 다른 방법으로 안내하겠다.)

## 현재 상태 — 축종 코드 확인 필요

지금은 **소고기(4301, 안심)** 만 연결돼 있다. 돼지고기·닭고기·오리고기 축종코드가 확인되면 `scripts/fetch-kbi-data.js` 안의 `SPECIES` 배열에 그대로 추가하면 된다. 코드만 알려주면 내가 바로 추가해서 다시 드리겠다.
