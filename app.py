import json
import pprint
import re
from urllib.parse import parse_qs, urlparse
from bs4 import BeautifulSoup
import pandas as pd
import requests
import streamlit as st

# =========================================================
# 기본 설정 및 인증키
# =========================================================
st.set_page_config(
    page_title="부산 청년·신혼 임대주택 매니저", page_icon="🏠", layout="wide"
)

# 모바일 및 웹 반응형 세련된 UI CSS
st.markdown(
    """
<style>
    /* 모바일 반응형 폰트 및 카드 여백 최적화 */
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.35rem !important;
        font-weight: 700 !important;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 6px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 12px;
        font-size: 14px;
        font-weight: 600;
    }
    .guide-box {
        background-color: #1e2530;
        border-radius: 10px;
        padding: 16px;
        margin-bottom: 16px;
        border-left: 4px solid #3b82f6;
    }
</style>
""",
    unsafe_allow_html=True,
)

SERVICE_KEY = "cd8ddb19a12f37c0cb2aa95a1e297c8eba46ceedb6a9ff9bf7c9549572314635"
LH_LEASE_URL = "https://apis.data.go.kr/B552555/lhLeaseInfo1/lhLeaseInfo1"

# =========================================================
# 1. 연도별 소득·자산 공식 DB (2026년 첨부 공고문 원문 반영)
# =========================================================
BENCHMARK_DB = {
    "2026": {
        "income_100": {
            1: 3813363,  # 1인 기본
            2: 5866270,  # 2인 기본
            3: 8168429,  # 3인 기본
            4: 8802202,  # 4인 기본
            5: 9326985,  # 5인 기본
            6: 9906263,  # 6인 기본
        },
        "per_additional": 579278,  # 7인 이상 1인당 추가액
        "assets": {
            "대학생": {
                "total_assets": 108000000,
                "car_value": 0,
                "desc": "자동차 소유 불가",
            },
            "청년": {
                "total_assets": 251000000,
                "car_value": 45420000,
                "desc": "청년 단독 자산 기준",
            },
            "신혼부부": {
                "total_assets": 345000000,
                "car_value": 45420000,
                "desc": "세대 총자산 기준",
            },
            "고령자": {
                "total_assets": 345000000,
                "car_value": 45420000,
                "desc": "세대 총자산 기준",
            },
            "주거급여수급자": {
                "total_assets": 345000000,
                "car_value": 45420000,
                "desc": "세대 총자산 기준",
            },
            "일반": {
                "total_assets": 345000000,
                "car_value": 45420000,
                "desc": "세대 총자산 기준",
            },
        },
    },
    "2025": {
        "income_100": {
            1: 3600000,
            2: 5500000,
            3: 7800000,
            4: 8400000,
            5: 8900000,
            6: 9400000,
        },
        "per_additional": 550000,
        "assets": {
            "대학생": {
                "total_assets": 100000000,
                "car_value": 0,
                "desc": "자동차 소유 불가",
            },
            "청년": {
                "total_assets": 240000000,
                "car_value": 40000000,
                "desc": "청년 단독 자산 기준",
            },
            "신혼부부": {
                "total_assets": 320000000,
                "car_value": 40000000,
                "desc": "세대 총자산 기준",
            },
            "고령자": {
                "total_assets": 320000000,
                "car_value": 40000000,
                "desc": "세대 총자산 기준",
            },
            "주거급여수급자": {
                "total_assets": 320000000,
                "car_value": 40000000,
                "desc": "세대 총자산 기준",
            },
            "일반": {
                "total_assets": 320000000,
                "car_value": 40000000,
                "desc": "세대 총자산 기준",
            },
        },
    },
}


# =========================================================
# 2. 공고 목록 수집 (마이홈 API)
# =========================================================
@st.cache_data(ttl=600)
def load_housing_data():
  url = "https://apis.data.go.kr/1613000/HWSPR02/rsdtRcritNtcList"
  params = {
      "serviceKey": SERVICE_KEY,
      "pageNo": "1",
      "numOfRows": "50",
      "brtcCode": "26",
      "suplyTyCode": "10",
  }
  try:
    resp = requests.get(url, params=params, timeout=10)
    items = resp.json().get("response", {}).get("body", {}).get("item", [])
    if not items:
      return pd.DataFrame()
    df = pd.DataFrame(items)

    def classify_recruit_type(title):
      title = str(title)
      return (
          "예비자모집"
          if any(k in title for k in ["예비입주자", "예비자", "예비"])
          else "신규공급"
      )

    def classify_target(row):
      title = str(row.get("pblancNm", ""))
      suply = str(row.get("suplyTyNm", ""))
      if suply == "행복주택" or "행복주택" in title:
        return "행복주택"
      elif "청년" in title and "매입임대" in suply:
        return "청년 매입임대"
      elif "신혼" in title and "매입임대" in suply:
        return "신혼부부 매입임대"
      return "기타"

    def parse_url_params(u):
      try:
        parsed = urlparse(str(u))
        qs = parse_qs(parsed.query)
        return {
            "panId": qs.get("panId", [""])[0],
            "ccr": qs.get("ccrCnntSysDsCd", ["03"])[0],
            "upp": qs.get("uppAisTpCd", ["06"])[0],
            "ais": qs.get("aisTpCd", ["10"])[0],
        }
      except Exception:
        return {"panId": "", "ccr": "03", "upp": "06", "ais": "10"}

    df["주택유형"] = df.apply(classify_target, axis=1)
    df["모집유형"] = df["pblancNm"].apply(classify_recruit_type)

    params_list = df["url"].apply(parse_url_params).tolist()
    df["PAN_ID"] = [p["panId"] for p in params_list]
    df["CCR_CNNT_SYS_DS_CD"] = [p["ccr"] for p in params_list]
    df["UPP_AIS_TP_CD"] = [p["upp"] for p in params_list]
    df["AIS_TP_CD"] = [p["ais"] for p in params_list]

    df_filtered = df[
        df["주택유형"].isin(["행복주택", "청년 매입임대", "신혼부부 매입임대"])
    ].copy()

    for col in ["beginDe", "endDe", "rcritPblancDe", "przwnerPresnatnDe"]:
      if col in df_filtered.columns:
        df_filtered[col] = df_filtered[col].apply(
            lambda x: (
                f"{str(x)[:4]}-{str(x)[4:6]}-{str(x)[6:]}"
                if len(str(x)) == 8
                else str(x)
            )
        )

    cols_map = {
        "모집유형": "모집유형",
        "주택유형": "주택유형",
        "pblancNm": "공고명",
        "signguNm": "자치구",
        "hsmpNm": "단지명",
        "sumSuplyCo": "모집호수",
        "beginDe": "접수시작일",
        "endDe": "접수마감일",
        "PAN_ID": "공고아이디",
        "CCR_CNNT_SYS_DS_CD": "CCR_CNNT_SYS_DS_CD",
        "UPP_AIS_TP_CD": "UPP_AIS_TP_CD",
        "AIS_TP_CD": "AIS_TP_CD",
        "url": "LH상세URL",
    }
    avail = [c for c in cols_map.keys() if c in df_filtered.columns]
    return df_filtered[avail].rename(columns=cols_map).reset_index(drop=True)
  except Exception as e:
    st.error(f"공고 목록 수집 오류: {e}")
    return pd.DataFrame()


# =========================================================
# 3. [공식 OpenAPI] 분양임대공고별 상세정보 조회 서비스 연동
# =========================================================
def fetch_lh_official_detail(
    pan_id, ccr_cd, upp_cd, ais_cd, title="", service_key=SERVICE_KEY
):
  endpoint = "https://apis.data.go.kr/B552555/lhLeaseNoticeDtlInfo1/getLeaseNoticeDtlInfo1"

  spl_inf_tp_cd = "063"
  if upp_cd == "06":
    if ais_cd == "10":
      spl_inf_tp_cd = "063"  # 행복주택
    elif ais_cd in ["07", "09", "48"]:
      spl_inf_tp_cd = "062"  # 국민/영구/통합
    elif ais_cd == "05":
      spl_inf_tp_cd = "060"
  elif upp_cd == "13":
    if "신혼" in title:
      spl_inf_tp_cd = "132"
    elif "청년" in title:
      spl_inf_tp_cd = "131"
    elif "전세형" in title:
      spl_inf_tp_cd = "143"
    elif "다자녀" in title:
      spl_inf_tp_cd = "141"
    else:
      spl_inf_tp_cd = "135"
  elif upp_cd == "05":
    spl_inf_tp_cd = "050"

  params = {
      "serviceKey": service_key,
      "SPL_INF_TP_CD": spl_inf_tp_cd,
      "CCR_CNNT_SYS_DS_CD": ccr_cd,
      "PAN_ID": pan_id,
      "UPP_AIS_TP_CD": upp_cd,
      "AIS_TP_CD": ais_cd,
  }

  try:
    resp = requests.get(endpoint, params=params, timeout=8)
    if resp.status_code != 200:
      return {}

    data = resp.json()
    merged = {}
    if isinstance(data, list):
      for block in data:
        if isinstance(block, dict):
          for k, v in block.items():
            if isinstance(v, list) and v and not k.endswith("Nm"):
              merged[k] = v
    elif isinstance(data, dict):
      merged = data
    return merged
  except Exception as e:
    st.warning(f"상세 API 조회 알림: {e}")
    return {}


# =========================================================
# 4. [신규 추가] lhLeaseInfo1 OpenAPI: 단지 내 평형별 물리적 세대수 전용 조회
# =========================================================
@st.cache_data(ttl=1800)
def fetch_lh_physical_units(complex_name: str, region_code: str = "26"):
  """LH 임대주택단지조회 OpenAPI(lhLeaseInfo1)를 활용하여

  단지 내 평형별 '물리적 총 세대수(예: 39.85㎡ 48세대, 44.88㎡ 96세대)' 정보를 조회합니다.
  """
  params = {
      "serviceKey": SERVICE_KEY,
      "PG_SZ": "50",
      "PAGE": "1",
      "CNP_CD": region_code,
      "SPL_TP_CD": "10",
  }
  try:
    resp = requests.get(LH_LEASE_URL, params=params, timeout=8)
    if resp.status_code != 200:
      return pd.DataFrame()

    data = resp.json()
    items = []
    if isinstance(data, list):
      for elem in data:
        if isinstance(elem, dict) and "dsList" in elem:
          items = elem["dsList"]
          break
    elif isinstance(data, dict):
      items = data.get("dsList", [])

    if not items:
      return pd.DataFrame()

    df = pd.DataFrame(items)

    clean_kw = re.sub(
        r"\[.*?\]|\(.*?\)|부산|1블록|2블록|행복주택|최초|입주자|모집",
        "",
        complex_name,
    ).strip()
    search_terms = [w for w in clean_kw.split() if len(w) >= 2]

    matched_df = pd.DataFrame()
    if "SBD_LGO_NM" in df.columns:
      for kw in search_terms:
        found = df[df["SBD_LGO_NM"].str.contains(kw, na=False, case=False)]
        if not found.empty:
          matched_df = found
          break

    if matched_df.empty:
      matched_df = df

    records = []
    for _, row in matched_df.iterrows():
      area_m2 = float(row.get("DDO_AR", 0))
      house_cnt = int(row.get("HSH_CNT", 0))
      pyung = round(area_m2 / 3.3058, 1)

      records.append({
          "단지명": row.get("SBD_LGO_NM", ""),
          "지역": row.get("ARA_NM", ""),
          "전용면적(㎡)": area_m2,
          "공급평형": f"{pyung}평형",
          "단지 물리적 세대수": f"{house_cnt}세대",
          "최초입주예정": row.get("MVIN_XPC_YM", "-"),
      })

    res_df = pd.DataFrame(records)
    if not res_df.empty and "전용면적(㎡)" in res_df.columns:
      res_df = res_df.sort_values(by="전용면적(㎡)").reset_index(drop=True)
    return res_df

  except Exception as e:
    print(f"LH 단지 세대수 조회 오류: {e}")
    return pd.DataFrame()


# =========================================================
# 사이드바: 기준 설정 및 사용자 입력 (맞벌이 전용 기능 강화)
# =========================================================
st.sidebar.header("⚙️ 기준 설정")
selected_year = st.sidebar.selectbox(
    "📅 소득·자산 적용 연도", list(BENCHMARK_DB.keys()), index=0
)
current_benchmark = BENCHMARK_DB[selected_year]

st.sidebar.divider()
st.sidebar.header("👤 내 신청 조건 입력")
target_type = st.sidebar.selectbox(
    "신청 계층", ["신혼부부", "청년", "대학생", "고령자", "주거급여수급자"]
)

is_dual = False
if target_type == "신혼부부":
  household_size = st.sidebar.slider(
      "가구원수 (부부 2인 이상)", min_value=2, max_value=6, value=2
  )
  is_dual = st.sidebar.checkbox(
      "👫 맞벌이 부부 여부 (소득한도 +20%p 완화 적용)", value=True
  )
  st.sidebar.caption(
      "💡 맞벌이 선택 시 2인 130%(762만), 3인 120%(980만)로 대폭 상향 적용됩니다."
  )
else:
  household_size = st.sidebar.slider(
      "가구원수 (본인 포함)", min_value=1, max_value=6, value=1
  )

has_baby = st.sidebar.selectbox(
    "23.3.28 이후 출산/입양 자녀(태아)",
    ["없음 (0명)", "1명 (+10% 가산)", "2명 이상 (+20% 가산)"],
)
baby_addon_rate = 20 if "2명" in has_baby else (10 if "1명" in has_baby else 0)

monthly_income = st.sidebar.number_input(
    "부부 합산 세전 월소득 (원)"
    if (target_type == "신혼부부" and is_dual)
    else "월평균 세전 소득 (원)",
    min_value=0,
    max_value=30000000,
    value=6500000 if (target_type == "신혼부부" and is_dual) else 3200000,
    step=100000,
)
total_assets = st.sidebar.number_input(
    "세대 총자산 가액 (원)",
    min_value=0,
    max_value=1000000000,
    value=180000000 if target_type == "신혼부부" else 120000000,
    step=5000000,
)
car_val = st.sidebar.number_input(
    "자동차 가액 (원, 없으면 0)",
    min_value=0,
    max_value=100000000,
    value=22000000,
    step=1000000,
)

# =========================================================
# 메인 헤더 및 탭 구성
# =========================================================
st.title("🏠 부산 청년·신혼 행복주택 올인원 매니저")
st.caption(
    f"적용 기준: {selected_year}년 국토교통부 고시 기준 | 맞벌이 신혼부부 특례 및"
    " 출산가산 공식 반영 | 모바일 최적화"
)

tab1, tab2, tab3, tab4 = st.tabs([
    "📋 입주자격 정밀진단",
    "🎯 우선공급 순위 & 배점",
    "🏢 실시간 공고 & 단지 상세",
    "💰 상호전환보증금 계산기",
])

# ---------------------------------------------------------
# 탭 1: 입주자격 정밀진단 (모바일 친화 2x2 카드 레이아웃)
# ---------------------------------------------------------
with tab1:
  st.subheader(
      f"📌 [{selected_year}년도 공고 기준] {target_type} 계층 자격 판정"
  )

  base_inc = (
      current_benchmark["income_100"][household_size]
      if household_size in current_benchmark["income_100"]
      else current_benchmark["income_100"][6]
      + (household_size - 6) * current_benchmark["per_additional"]
  )

  if target_type == "신혼부부":
    if is_dual:
      base_ratio_100 = 130 if household_size == 2 else 120
      base_ratio_80 = 110 if household_size == 2 else 100
    else:
      base_ratio_100 = 110 if household_size == 2 else 100
      base_ratio_80 = 90 if household_size == 2 else 80
  elif household_size == 1:
    base_ratio_100 = 120
    base_ratio_80 = 100
  elif household_size == 2:
    base_ratio_100 = 110
    base_ratio_80 = 90
  else:
    base_ratio_100 = 100
    base_ratio_80 = 80

  effective_income_ratio = base_ratio_100 + baby_addon_rate
  effective_80_ratio = base_ratio_80 + baby_addon_rate

  income_limit_100 = int(base_inc * (effective_income_ratio / 100.0))
  income_limit_80 = int(base_inc * (effective_80_ratio / 100.0))

  asset_cfg = current_benchmark["assets"][target_type]
  effective_asset_limit = int(
      asset_cfg["total_assets"] * (1 + baby_addon_rate / 100.0)
  )
  effective_car_limit = int(
      asset_cfg["car_value"] * (1 + baby_addon_rate / 100.0)
  )

  pass_inc = monthly_income <= income_limit_100
  pass_inc80 = monthly_income <= income_limit_80
  pass_asset = total_assets <= effective_asset_limit
  pass_car = (
      (car_val == 0)
      if target_type == "대학생"
      else car_val <= effective_car_limit
  )

  if target_type == "신혼부부" and is_dual:
    st.info(
        f"👫 **맞벌이 신혼부부 특례 적용 중**: 일반 소득 기준(100%) 대비 **+20%p"
        f" 완화** (현재 {household_size}인가구: **{effective_income_ratio}%**"
        " 적용)"
    )

  # 모바일 화면 최적화: 4열 대신 2열씩 2줄 배치로 찌그러짐 방지
  c1, c2 = st.columns(2)
  with c1:
    st.metric(
        label=f"월소득 100% 기준 ({effective_income_ratio}%)",
        value=f"{monthly_income:,}원",
        delta=(
            f"{income_limit_100 - monthly_income:,}원 여유"
            if pass_inc
            else f"{monthly_income - income_limit_100:,}원 초과"
        ),
        delta_color="normal" if pass_inc else "inverse",
    )
    st.caption(f"상한액: {income_limit_100:,}원 이하")
  with c2:
    st.metric(
        label=f"월소득 80% 기준 ({effective_80_ratio}%)",
        value=f"{monthly_income:,}원",
        delta=(
            f"{income_limit_80 - monthly_income:,}원 여유"
            if pass_inc80
            else f"{monthly_income - income_limit_80:,}원 초과"
        ),
        delta_color="normal" if pass_inc80 else "inverse",
    )
    st.caption(f"상한액: {income_limit_80:,}원 이하")

  st.write("")
  c3, c4 = st.columns(2)
  with c3:
    st.metric(
        label="총자산 기준 (출산가산 반영)",
        value=f"{total_assets // 10000:,}만 원",
        delta=(
            f"{(effective_asset_limit - total_assets) // 10000:,}만 원 여유"
            if pass_asset
            else "기준 초과 ❌"
        ),
        delta_color="normal" if pass_asset else "inverse",
    )
    st.caption(f"상한액: {effective_asset_limit // 10000:,}만 원 이하")
  with c4:
    st.metric(
        label="자동차 가액 기준",
        value=f"{car_val // 10000:,}만 원",
        delta="기준 충족 ✅" if pass_car else "기준 초과 ❌",
        delta_color="normal" if pass_car else "inverse",
    )
    st.caption(
        f"상한액: {effective_car_limit // 10000:,}만 원 이하"
        if target_type != "대학생"
        else "차량 소유 불가"
    )

  st.divider()
  if pass_inc and pass_asset and pass_car:
    st.success(
        f"🎉 **{target_type} ({'맞벌이' if is_dual else '외벌이'}) 계층** 기본"
        " 입주자격을 모두 충족합니다!"
    )
  else:
    st.warning("⚠️ 일부 기준을 초과하였습니다. 세부 항목을 확인해 주세요.")

  if target_type == "신혼부부":
    with st.expander("📊 [참고] 신혼부부 외벌이 vs 맞벌이 소득 한도 비교표"):
      comp_data = []
      for sz in range(2, 7):
        b = current_benchmark["income_100"][sz]
        single_r = 110 if sz == 2 else 100
        dual_r = 130 if sz == 2 else 120
        comp_data.append({
            "가구원수": f"{sz}인 가구",
            "외벌이 기준": f"{int(b * (single_r / 100)):,}원 ({single_r}%)",
            "맞벌이 기준 (+20%p)": f"{int(b * (dual_r / 100)):,}원 ({dual_r}%)",
            "소득 한도 차이": (
                f"+{int(b * (dual_r / 100)) - int(b * (single_r / 100)):,}원"
            ),
        })
      st.dataframe(
          pd.DataFrame(comp_data), use_container_width=True, hide_index=True
      )

# ---------------------------------------------------------
# 탭 2: 우선공급 순위 & 배점 체크
# ---------------------------------------------------------
with tab2:
  st.subheader("🎯 우선공급 대상자 자격 및 배점 체크")
  st.info(
      "💡 **[공고문 공식 규정]** 우선공급에서 탈락한 신청자는 **별도의 신청 절차 없이"
      " 자동으로 일반공급 신청자로 전환**되어 추첨에 참여합니다."
  )

  st.markdown("#### 1) 공급 순위 판정")
  if target_type == "신혼부부":
    residence = st.radio(
        "거주지 (신청자 본인 기준)",
        [
            "1순위: 신청자 본인이 행복주택 위치 자치구에 거주",
            "2순위: 신청자 본인이 해당 구 외 부산광역시에 거주",
            "3순위: 기타 경남/울산 및 전국 지역",
        ],
    )
  elif target_type in ["청년", "고령자", "주거급여수급자"]:
    residence = st.radio(
        "거주지 또는 소득 근거지(직장)",
        [
            "1순위: 부산광역시 해당 자치구 거주 또는 소득 근거지",
            "2순위: 해당 자치구 외 부산광역시 거주 또는 소득 근거지",
            "3순위: 기타 경남/울산 및 전국 지역",
        ],
    )
  else:
    residence = st.radio(
        "대학 소재지 또는 거주지",
        [
            (
                "1순위: 해당 자치구 소재 대학 재학/입학예정자 (취준생: 해당 구"
                " 거주)"
            ),
            "2순위: 해당 구 외 부산시 소재 대학 재학/입학예정자",
            "3순위: 기타 지역",
        ],
    )

  st.markdown("#### 2) 가점(배점) 계산 체크란")
  score = 0
  if target_type in ["청년", "신혼부부"]:
    c_res = st.selectbox(
        "① 해당 구 거주기간 (우선 1순위만 적용)",
        [
            "해당 자치구 3년 이상 계속 거주 (3점)",
            "해당 자치구 3년 미만 계속 거주 (1점)",
            "해당 구 외 거주 (0점)",
        ],
    )
    if "3점" in c_res and "1순위" in residence:
      score += 3
    elif "1점" in c_res and "1순위" in residence:
      score += 1

    c_bank = st.selectbox(
        "② 청약통장 납입횟수 (신혼부부는 본인 또는 배우자 중 1인)",
        [
            "가입 2년 경과 + 24회 이상 납입 (3점)",
            "가입 6개월 경과 + 6회~23회 납입 (1점)",
            "6회 미만 납입 (0점)",
        ],
    )
    if "3점" in c_bank:
      score += 3
    elif "1점" in c_bank:
      score += 1

  elif target_type == "대학생":
    d_res = st.selectbox(
        "부모 거주지 (대학생) 또는 본인 거주기간 (취준생)",
        [
            "부모 모두 부산 외 거주 / 취준생 해당 구 3년 이상 거주 (3점)",
            "부모 1인 이상 부산 거주 / 취준생 해당 구 3년 미만 거주 (1점)",
            "해당 없음 (0점)",
        ],
    )
    if "3점" in d_res and "1순위" in residence:
      score += 3
    elif "1점" in d_res and "1순위" in residence:
      score += 1
  else:
    g_res = st.selectbox(
        "거주기간 배점",
        [
            "해당 구 5년 이상 거주 (3점)",
            "해당 구 5년 미만 거주 (2점)",
            "기타 부산 거주 (1점)",
        ],
    )
    if "3점" in g_res:
      score += 3
    elif "2점" in g_res:
      score += 2
    elif "1점" in g_res:
      score += 1

  r_col1, r_col2 = st.columns(2)
  with r_col1:
    st.metric("최종 판정 순위", residence.split(":")[0])
  with r_col2:
    st.metric("총 획득 가점(배점)", f"{score} 점")

# ---------------------------------------------------------
# 탭 3: 실시간 공고 & 단지 상세 조회 (LH 공식 세대수 API 탑재)
# ---------------------------------------------------------
with tab3:
  st.subheader("📢 실시간 부산 임대 공고 & 단지별 세부 정보")
  df_notices = load_housing_data()

  if df_notices.empty:
    st.info("현재 모집 중인 공고를 불러올 수 없습니다.")
  else:
    c1, c2 = st.columns(2)
    with c1:
      r_filter = st.multiselect(
          "모집 유형",
          ["신규공급", "예비자모집"],
          default=["신규공급", "예비자모집"],
      )
    with c2:
      d_list = df_notices["자치구"].dropna().unique().tolist()
      d_filter = st.multiselect("자치구 필터", d_list, default=d_list)

    filtered = df_notices[
        (df_notices["모집유형"].isin(r_filter))
        & (df_notices["자치구"].isin(d_filter))
    ]

    st.dataframe(
        filtered[[
            "모집유형",
            "주택유형",
            "공고명",
            "자치구",
            "단지명",
            "모집호수",
            "접수시작일",
            "접수마감일",
            "공고아이디",
        ]],
        use_container_width=True,
        hide_index=True,
    )

    st.divider()

    selected_idx = st.selectbox(
        "상세 정보를 확인할 공고를 선택하세요:",
        range(len(filtered)),
        format_func=lambda x: (
            f"[{filtered.iloc[x]['모집유형']}] {filtered.iloc[x]['공고명']} (ID:"
            f" {filtered.iloc[x]['공고아이디']})"
        ),
    )

    target_row = filtered.iloc[selected_idx]
    pan_id = target_row.get("공고아이디", "")
    ccr_cd = target_row.get("CCR_CNNT_SYS_DS_CD", "03")
    upp_cd = target_row.get("UPP_AIS_TP_CD", "06")
    ais_cd = target_row.get("AIS_TP_CD", "10")
    notice_title = target_row.get("공고명", "")

    # -------------------------------------------------------------
    # [신규 탑재] lhLeaseInfo1 OpenAPI: 단지 내 평형별 물리적 세대수
    # -------------------------------------------------------------
    st.markdown("#### 🏢 1. [LH 단지 마스터] 평형별 물리적 총 세대수")
    st.caption(
        "※ lhLeaseInfo1 OpenAPI를 통해 해당 단지의 건축 설계상 평형별 전체 세대수(물리적"
        " 호수)를 확인합니다."
    )

    df_phys = fetch_lh_physical_units(complex_name=notice_title)
    if not df_phys.empty:
      m1, m2 = st.columns(2)
      m1.metric("확인 단지명", df_phys.iloc[0]["단지명"])
      tot_units = sum([
          int(str(x).replace("세대", ""))
          for x in df_phys["단지 물리적 세대수"]
          if str(x).replace("세대", "").isdigit()
      ])
      m2.metric("단지 전체 물리적 세대수", f"{tot_units:,}세대")

      st.dataframe(
          df_phys[[
              "단지명",
              "공급평형",
              "전용면적(㎡)",
              "단지 물리적 세대수",
              "지역",
              "최초입주예정",
          ]],
          use_container_width=True,
          hide_index=True,
      )
    else:
      st.info(
          "해당 공고의 LH 단지 마스터 세대수 데이터(lhLeaseInfo1)를 불러오는"
          " 중입니다..."
      )

    st.markdown("---")

    # -------------------------------------------------------------
    # 공식 상세정보 및 첨부파일
    # -------------------------------------------------------------
    st.markdown("#### 🔍 2. [공고 상세 공식정보] 접수일정 · 첨부파일")

    col_b1, col_b2 = st.columns(2)
    with col_b1:
      query_btn = st.button(
          "📋 LH 공식 상세정보 실시간 호출",
          type="primary",
          use_container_width=True,
      )
    with col_b2:
      if target_row.get("LH상세URL"):
        st.link_button(
            "🌐 LH 청약플러스 공식 웹페이지 이동",
            target_row["LH상세URL"],
            use_container_width=True,
        )

    if query_btn:
      with st.spinner("공공데이터포털 LH 공식 상세 API 호출 중..."):
        detail_json = fetch_lh_official_detail(
            pan_id, ccr_cd, upp_cd, ais_cd, notice_title
        )

        if detail_json:
          st.success(f"✅ 공고 ID [{pan_id}] 공식 상세 데이터 수신 완료")

          # 1) 단지 정보 및 전용면적 (dsSbd)
          if "dsSbd" in detail_json:
            st.markdown("##### 🏢 단지 기본정보 및 전용면적")
            sbd_df = pd.DataFrame(detail_json["dsSbd"])
            rename_sbd = {
                "LCC_NT_NM": "단지명",
                "BZDT_NM": "단지명",
                "DDO_AR": "전용면적(㎡)",
                "MIN_MAX_RSDN_DDO_AR": "전용면적(㎡)",
                "HSH_CNT": "총세대수",
                "SUM_TOT_HSH_CNT": "총세대수",
                "LGDN_ADR": "주소",
                "LCT_ARA_ADR": "주소",
                "HTN_FMLA_DESC": "난방방식",
                "MVIN_XPC_YM": "입주예정월",
            }
            display_cols = [
                c for c in rename_sbd.keys() if c in sbd_df.columns
            ]
            st.dataframe(
                sbd_df[display_cols].rename(columns=rename_sbd),
                use_container_width=True,
                hide_index=True,
            )

          # 2) 공식 첨부파일 직통 다운로드 (dsAhflInfo)
          if "dsAhflInfo" in detail_json:
            st.markdown("##### 📁 공식 첨부파일 (공고문 PDF / HWP)")
            ahfl_df = pd.DataFrame(detail_json["dsAhflInfo"])
            for _, f_row in ahfl_df.iterrows():
              f_name = f_row.get("CMN_AHFL_NM", "첨부파일")
              f_url = f_row.get("AHFL_URL", "")
              f_type = f_row.get("SL_PAN_AHFL_DS_CD_NM", "파일")
              if f_url:
                st.markdown(f"• **[{f_type}]** [{f_name}]({f_url})")

          # 3) 청약 및 계약 상세 일정 (dsSplScdl)
          if "dsSplScdl" in detail_json:
            st.markdown("##### 📅 세부 접수 및 발표 일정")
            scdl_df = pd.DataFrame(detail_json["dsSplScdl"])
            scdl_map = {
                "SBSC_ACP_ST_DT": "접수시작일",
                "SBSC_ACP_CLSG_DT": "접수종료일",
                "PPR_SBM_OPE_ANC_DT": "서류제출발표일",
                "PPR_ACP_ST_DT": "서류접수시작일",
                "PPR_ACP_CLSG_DT": "서류접수마감일",
                "PZWR_ANC_DT": "당첨자발표일",
                "CTRT_ST_DT": "계약시작일",
                "CTRT_ED_DT": "계약종료일",
            }
            show_scdl = [c for c in scdl_map.keys() if c in scdl_df.columns]
            st.dataframe(
                scdl_df[show_scdl].rename(columns=scdl_map),
                use_container_width=True,
                hide_index=True,
            )

          # 4) 접수처 / 현장 문의처 (dsCtrtPlc)
          if "dsCtrtPlc" in detail_json:
            st.markdown("##### 📞 접수처 및 문의처")
            plc_list = detail_json["dsCtrtPlc"]
            for plc in plc_list:
              addr = plc.get("CTRT_PLC_ADR", "")
              tel = plc.get("SIL_OFC_TLNO", "")
              st.write(
                  f"- **접수처**: {addr} (문의 전화: {tel or '1600-1004'})"
              )
        else:
          st.warning(
              "해당 공고는 LH 상세 API에서 아직 세부 공급 정보가 등록되지"
              " 않았거나, 다가구 매입임대 공고입니다.\n\n"
              "정확한 계층별 배정 및 공고문 원본(PDF)은 우측 **'🌐 LH 청약플러스 공식"
              " 웹페이지 이동'** 버튼을 통해 확인해 주세요."
          )

# ---------------------------------------------------------
# 탭 4: 상호전환보증금 계산기 (초보자 친절 설명 및 UI 개편)
# ---------------------------------------------------------
with tab4:
  st.subheader("💡 상호전환보증금(월 주거비) 시뮬레이션")

  # 처음 쓰는 사용자를 위한 친절한 설명 박스
  st.markdown(
      """
    <div class="guide-box">
        <h4>🙋‍♂️ 상호전환보증금이란 무엇인가요?</h4>
        <p>임대주택 입주 시 <b>보증금을 더 내고 매달 내는 월세를 깎는(월세 절감)</b> 아주 유용한 제도입니다.</p>
        <ul>
            <li><b>왜 보증금을 올리는 게 유리할까요?</b><br>
            LH가 월세를 깎아주는 이율(전환이율 <b>연 6~7%</b>)이 정부 지원 청년·신혼 버팀목 대출 금리(<b>연 1.5~2.4%</b>)보다 2배 이상 높기 때문입니다!</li>
            <li><b>실제 효과:</b><br>
            버팀목 전세대출을 받아 보증금을 최대로 높이면, 매달 대출이자를 내더라도 <b>기본 월세보다 매달 5~15만 원 이상의 순수 주거비를 절약</b>할 수 있습니다.</li>
        </ul>
        <p style="margin-bottom:0px;">👇 아래에서 공고문의 기본 보증금과 월세를 입력하고 슬라이더를 움직여 절감액을 확인해 보세요!</p>
    </div>
    """,
      unsafe_allow_html=True,
  )

  s1, s2 = st.columns(2)
  with s1:
    st.markdown("##### 1️⃣ 기본 임대 조건 입력")
    base_dep = st.number_input(
        "기본 보증금 (만원)",
        value=6000,
        step=100,
        help="공고문에 적힌 기본 계약 보증금",
    )
    base_rent = st.number_input(
        "기본 월세 (원)",
        value=275000,
        step=10000,
        help="공고문에 적힌 기본 월임대료",
    )

  with s2:
    st.markdown("##### 2️⃣ 추가 보증금 및 대출 설정")
    add_dep = st.slider(
        "추가 납부할 전환보증금 (만원)",
        min_value=0,
        max_value=6000,
        value=3000,
        step=100,
        help="보증금을 더 낼수록 월세가 깎입니다.",
    )
    loan_rate = (
        st.slider(
            "청년 버팀목 대출 금리 (연 %)",
            min_value=1.5,
            max_value=3.5,
            value=2.1,
            step=0.1,
            help="보통 청년 버팀목 전세대출은 연 1.8% ~ 2.4% 수준입니다.",
        )
        / 100.0
    )

  # 상호전환 계산 (전환이율 연 6% 기준)
  reduced_r = (add_dep * 10000) * (0.06 / 12)
  final_rent = max(base_rent - reduced_r, 0)
  monthly_interest = (add_dep * 10000) * (loan_rate / 12)
  total_expense = final_rent + monthly_interest
  monthly_savings = base_rent - total_expense

  st.markdown("---")
  st.markdown("##### 📊 전환 시뮬레이션 결과 비교")

  # 모바일 화면을 고려한 결과 카드 배치
  res1, res2 = st.columns(2)
  with res1:
    st.metric(
        label="최종 전환 보증금",
        value=f"{(base_dep + add_dep):,}만 원",
        delta=f"+{add_dep:,}만 원 증액",
    )
    st.caption("기본 보증금 + 추가 납부액")
  with res2:
    st.metric(
        label="깎인 최종 월세",
        value=f"{int(final_rent):,}원",
        delta=f"-{int(base_rent - final_rent):,}원 절감",
        delta_color="normal",
    )
    st.caption(f"기존 {base_rent:,}원에서 대폭 인하")

  st.write("")
  st.success(
      f"🎉 **최종 월 실부담금 (월세 + 대출이자): {int(total_expense):,}원**\n\n"
      f"👉 기본 조건으로 입주할 때보다 **매달 {int(monthly_savings):,}원을 순수하게 아낄 수 있습니다!**"
  )
