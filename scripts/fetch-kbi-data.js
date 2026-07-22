// KBI 데이터 자동 갱신 스크립트
// 축산물품질평가원 "일자별 축산물소비자가격 정보" API를 호출해서
// 17개 시도 소비자가격을 받아와 data/kbi-prices.json 으로 저장한다.
//
// 표준 장바구니 = 소고기 3부위(등심·양지·갈비) 각 1kg + 돼지고기 2부위(삼겹살·목심) 각 1kg
//                + 닭고기(육계) 1kg  → 총 6kg
// 부위를 평균내지 않고 각각 따로 저장해서, 페이지에서 부위별로 1kg씩 합산한다.

const fs = require("fs");
const path = require("path");

const SERVICE_KEY = process.env.EKAPE_SERVICE_KEY;
if (!SERVICE_KEY) {
  console.error("EKAPE_SERVICE_KEY 환경변수가 없습니다. GitHub 저장소 Secrets에 등록됐는지 확인하세요.");
  process.exit(1);
}

const BASE_URL = "http://data.ekape.or.kr/openapi-data/service/user/grade/consumerPriceDaily";

const REGION_NAMES = [
  "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
  "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"
];

const SPECIES = [
  {
    key: "beef", label: "소고기", judgeKind: "4301", unitScale: 10,
    cuts: [
      { key: "sirloin", name: "등심", itemCd: "22" },
      { key: "brisket", name: "양지", itemCd: "40" },
      { key: "ribs", name: "갈비", itemCd: "50" }
    ]
  },
  {
    key: "pork", label: "돼지고기", judgeKind: "4304", unitScale: 10,
    cuts: [
      { key: "belly", name: "삼겹살", itemCd: "27" },
      { key: "neck", name: "목심", itemCd: "68" }
    ]
  },
  {
    key: "chicken", label: "닭고기", judgeKind: "9901", unitScale: 1,
    cuts: [
      { key: "broiler", name: "육계", itemCd: "99" }
    ]
  }
];

function todayYmd() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}${m}${day}`;
}

function extractTag(xml, tagName) {
  const match = xml.match(new RegExp(`<${tagName}>([^<]*)</${tagName}>`));
  return match ? match[1].trim() : null;
}

async function fetchOneCut(judgeKind, itemCd, standYmd, unitScale) {
  const url = `${BASE_URL}?serviceKey=${SERVICE_KEY}&standYmd=${standYmd}&judgeKind=${judgeKind}&itemCd=${itemCd}`;
  const res = await fetch(url);
  const xml = await res.text();

  const resultCode = extractTag(xml, "resultCode");
  if (resultCode !== "00") {
    const msg = extractTag(xml, "resultMsg") || "알 수 없는 오류";
    throw new Error(`resultCode=${resultCode}: ${msg} / 원본응답: ${xml.slice(0, 200)}`);
  }

  const regionPrices = {};
  REGION_NAMES.forEach((name, idx) => {
    const tag = `regionPrc${idx + 1}`;
    const val = extractTag(xml, tag);
    regionPrices[name] = val !== null ? Math.round(Number(val) * unitScale) : null;
  });
  return regionPrices;
}

async function fetchSpecies(species) {
  const standYmd = todayYmd();
  const cutsOut = {};

  for (const cut of species.cuts) {
    try {
      const regionPrices = await fetchOneCut(species.judgeKind, cut.itemCd, standYmd, species.unitScale);
      cutsOut[cut.key] = { name: cut.name, unit: "원/1kg", regionPrices: regionPrices };
      console.log(`  [OK] ${species.label} - ${cut.name}`);
    } catch (err) {
      console.error(`  [FAIL] ${species.label} - ${cut.name}: ${err.message}`);
      cutsOut[cut.key] = { name: cut.name, unit: "원/1kg", regionPrices: null, error: err.message };
    }
  }

  return { label: species.label, cuts: cutsOut };
}

async function main() {
  const result = {
    updatedAt: new Date().toISOString(),
    source: "축산물품질평가원 축산유통정보(다봄) - 일자별 축산물소비자가격 정보 (부위별 1kg 가격, 평균 아님)",
    species: {}
  };

  for (const species of SPECIES) {
    console.log(`${species.label} 조회 시작...`);
    result.species[species.key] = await fetchSpecies(species);
  }

  const outDir = path.join(__dirname, "..", "data");
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(
    path.join(outDir, "kbi-prices.json"),
    JSON.stringify(result, null, 2),
    "utf-8"
  );

  console.log("data/kbi-prices.json 저장 완료");
}

main();
