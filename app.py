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

SERVICE_KEY = "cd8ddb19a12f37c0cb2aa95a1e297c8eba46ceedb6a9ff9bf7c9549572314635"

# =========================================================
# 1. 연도별 소득·자산 공식 DB (2026년 기준)
# =========================================================
BENCHMARK_DB = {
    "2026": {
        "income_100": {
            1: 3813363,
            2: 5866270,
            3: 8168429,
            4: 8802202,
            5: 9326985,
            6: 9906263,
        },
        "per_additional": 579278,
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
        items = (
            resp.json().get("response", {}).get("body", {}).get("item", [])
        )
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
                    lambda x: f"{str(x)[:4]}-{str(x)[4:6]}-{str(x)[6:]}"
                    if len(str(x)) == 8
                    else str(x)
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
            "mobileUrl": "상세모바일URL",
            "url": "LH상세URL",
        }
        avail = [c for c in cols_map.keys() if c in df_filtered.columns]
        return (
            df_filtered[avail].rename(columns=cols_map).reset_index(drop=True)
        )
    except Exception as e:
        st.error(f"공고 목록 수집 오류: {e}")
        return pd.DataFrame()


# =========================================================
# 3. [완전 동적 추출] 선택 공고의 세부 평형/계층/우선/일반 실시간 파서
# =========================================================
def fetch_dynamic_unit_breakdown(mobile_url: str):
    """어떤 공고든 모바일 상세 URL을 분석하여 평형, 공급대상계층, 총모집, 우선공급,

    일반공급, 기본보증금, 월세를 100% 동적으로 파싱합니다.
    """
    if not mobile_url:
        return pd.DataFrame()

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://m.myhome.go.kr/",
    }

    try:
        resp = requests.get(mobile_url, headers=headers, timeout=6)
        if resp.status_code != 200:
            return pd.DataFrame()
        text = BeautifulSoup(resp.text, "html.parser").get_text(separator="\n")
    except Exception:
        return pd.DataFrame()

    # 모든 마이홈 공급표 서식에 맞춘 범용 정규표현식
    pattern = re.compile(
        r"([0-9a-zA-Z가-힣.()\-_/]+)\s*\.?\s*"
        r"전용면적\s*([0-9.]+)\s*㎡\s*"
        r"월임대료(?:\(원\))?\s*([0-9,]+)\s*\.?\s*"
        r"계\s*([0-9,]+)\s*(?:세대|호)?\s*우선공급\s*([0-9,]+)\s*(?:세대|호)?\s*일반공급\s*([0-9,]+)\s*\.?\s*"
        r"계\s*([0-9,]+)",
        re.DOTALL,
    )

    results = []
    for m in pattern.finditer(text):
        h_type = m.group(1).strip()
        area_m2 = float(m.group(2))
        monthly_rent = int(m.group(3).replace(",", ""))
        total_supply = int(m.group(4).replace(",", ""))
        priority_supply = int(m.group(5).replace(",", ""))
        general_supply = int(m.group(6).replace(",", ""))
        deposit = int(m.group(7).replace(",", ""))

        # 공급대상 계층 자동 추출
        target = "일반"
        if "청년" in h_type:
            target = "청년"
        elif "신혼" in h_type or "한부모" in h_type:
            target = "신혼부부·한부모"
        elif "대학생" in h_type:
            target = "대학생"
        elif "고령자" in h_type or "주거약자" in h_type:
            target = "고령자"
        elif "주거급여" in h_type or "수급자" in h_type:
            target = "주거급여수급자"
        elif "장애인" in h_type:
            target = "장애인"

        results.append({
            "주택형": h_type,
            "공급대상 계층": target,
            "전용면적(㎡)": area_m2,
            "평수": round(area_m2 / 3.3058, 1),
            "총 모집호수": total_supply,
            "우선공급": priority_supply,
            "일반공급": general_supply,
            "기본보증금": f"{deposit:,}원",
            "월임대료": f"{monthly_rent:,}원",
        })

    return pd.DataFrame(results)


# =========================================================
# 4. [공식 OpenAPI] 분양임대공고별 상세정보 조회 서비스 연동
# =========================================================
def fetch_lh_official_detail(
    pan_id, ccr_cd, upp_cd, ais_cd, title="", service_key=SERVICE_KEY
):
    endpoint = "https://apis.data.go.kr/B552555/lhLeaseNoticeDtlInfo1/getLeaseNoticeDtlInfo1"

    spl_inf_tp_cd = "063"
    if upp_cd == "06":
        if ais_cd == "10":
            spl_inf_tp_cd = "063"
        elif ais_cd in ["07", "09", "48"]:
            spl_inf_tp_cd = "062"
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
    except Exception:
        return {}


# =========================================================
# 사이드바: 기준 설정 및 사용자 입력
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
    st.sidebar.caption("💡 2인 맞벌이: 130%(762만), 3인 맞벌이: 120%(980만)")
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
    f"적용 기준: {selected_year}년 국토교통부 고시 기준 | 공고별 실시간 주택형·우선/일반 모집호수 동적 추출"
)

tab1, tab2, tab3, tab4 = st.tabs([
    "📋 입주자격 정밀진단",
    "🎯 우선공급 순위 & 배점 체크",
    "🏢 실시간 공고 & 단지 상세 조회",
    "💰 상호전환보증금 계산기",
])

# ---------------------------------------------------------
# 탭 1: 입주자격 정밀진단
# ---------------------------------------------------------
with tab1:
    st.subheader(
        f"📌 [{selected_year}년도 공고 기준] {target_type} 계층 자격 판정"
    )

    base_inc = (
        current_benchmark["income_100"][household_size]
        if household_size in current_benchmark["income_100"]
        else current_benchmark["income_100"]
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
        (car_val == 0) if target_type == "대학생" else car_val <= effective_car_limit
    )

    if target_type == "신혼부부" and is_dual:
        st.info(
            f"👫 **맞벌이 신혼부부 특례 적용 중**: 일반 소득 기준(100%) 대비 **+20%p 완화** (현재 {household_size}인 가구: **{effective_income_ratio}%** 적용)"
        )

    c1, c2, c3, c4 = st.columns(4)
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
    with c3:
        st.metric(
            label="총자산 기준 (출산가산 반영)",
            value=f"{total_assets // 10000:,}만 원",
            delta=(
                f"{(effective_asset_limit - total_assets) // 10000:,}만 원 여유"
                if pass_asset
                else "초과"
            ),
            delta_color="normal" if pass_asset else "inverse",
        )
        st.caption(f"상한액: {effective_asset_limit // 10000:,}만 원 이하")
    with c4:
        st.metric(
            label="자동차 가액 기준",
            value=f"{car_val // 10000:,}만 원",
            delta="충족" if pass_car else "초과",
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
            f"🎉 **{target_type} ({'맞벌이' if is_dual else '외벌이'}) 계층** 기본 입주자격을 모두 충족합니다!"
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
                    "외벌이 기준": (
                        f"{int(b * (single_r/100)):,}원 ({single_r}%)"
                    ),
                    "맞벌이 기준 (+20%p)": (
                        f"{int(b * (dual_r/100)):,}원 ({dual_r}%)"
                    ),
                    "소득 한도 차이": (
                        f"+{int(b * (dual_r/100)) - int(b * (single_r/100)):,}원"
                    ),
                })
            st.table(pd.DataFrame(comp_data))

# ---------------------------------------------------------
# 탭 2: 우선공급 순위 & 배점 체크
# ---------------------------------------------------------
with tab2:
    st.subheader("🎯 우선공급 대상자 자격 및 배점 체크")
    st.info(
        "💡 **[공고문 공식 규정]** 우선공급에서 탈락한 신청자는 **별도의 신청 절차 없이 자동으로 일반공급 신청자로 전환**되어 추첨에 참여합니다."
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
                "1순위: 해당 자치구 소재 대학 재학/입학예정자 (취준생: 해당 구 거주)",
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
            ["해당 구 5년 이상 거주 (3점)", "해당 구 5년 미만 거주 (2점)", "기타 부산 거주 (1점)"],
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
# 탭 3: 실시간 공고 & 평형별·계층별 세부 모집호수 동적 조회
# ---------------------------------------------------------
with tab3:
    st.subheader("📢 실시간 부산 임대 공고 & 평형별·계층별 세부 모집인원")
    df_notices = load_housing_data()

    if df_notices.empty:
        st.info("현재 모집 중인 공고를 불러올 수 없습니다.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            r_filter = st.multiselect(
                "모집 유형", ["신규공급", "예비자모집"], default=["신규공급", "예비자모집"]
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
        st.markdown(
            "#### 🔍 [실시간 동적 추출] 선택 공고의 공급대상계층 · 평수별 세부 배정표"
        )

        selected_idx = st.selectbox(
            "상세 정보를 확인할 공고를 선택하세요:",
            range(len(filtered)),
            format_func=lambda x: f"[{filtered.iloc[x]['모집유형']}] {filtered.iloc[x]['공고명']} (ID: {filtered.iloc[x]['공고아이디']})",
        )

        target_row = filtered.iloc[selected_idx]
        pan_id = target_row.get("공고아이디", "")
        ccr_cd = target_row.get("CCR_CNNT_SYS_DS_CD", "03")
        upp_cd = target_row.get("UPP_AIS_TP_CD", "06")
        ais_cd = target_row.get("AIS_TP_CD", "10")
        notice_title = target_row.get("공고명", "")
        mobile_url = target_row.get("상세모바일URL", "")

        col_b1, col_b2 = st.columns(2)
        with col_b1:
            query_btn = st.button("공고 세부 평형 및 우선/일반 배정표 실시간 추출")
        with col_b2:
            if target_row.get("LH상세URL"):
                st.link_button(
                    "🌐 LH 청약플러스 공식 웹페이지 이동",
                    target_row["LH상세URL"],
                )

        if query_btn:
            with st.spinner("해당 공고의 실시간 공급 정보를 추출 중입니다..."):
                # 1. 공고별 실시간 공급 정보 동적 파싱 (하드코딩 제거)
                df_units = fetch_dynamic_unit_breakdown(mobile_url)

                if not df_units.empty:
                    st.success(
                        f"✅ [{notice_title}] 세부 평형 데이터 추출 완료 (총 {len(df_units)}개 주택형)"
                    )

                    # 내 계층 맞춤형 요약 카드
                    target_keyword = (
                        "신혼" if target_type == "신혼부부" else target_type[:2]
                    )
                    my_units = df_units[
                        df_units["공급대상 계층"].str.contains(target_keyword)
                    ]

                    if not my_units.empty:
                        st.markdown(
                            f"##### 🎯 [{target_type} 계층] 지원 가능 주택형 및 모집 규모 요약"
                        )
                        for _, u_row in my_units.iterrows():
                            uc1, uc2, uc3, uc4 = st.columns(4)
                            uc1.metric(
                                "주택형 (평수)",
                                f"{u_row['주택형']} ({u_row['평수']}평)",
                            )
                            uc2.metric(
                                "우선공급 인원", f"{u_row['우선공급']} 명"
                            )
                            uc3.metric(
                                "일반공급 인원", f"{u_row['일반공급']} 명"
                            )
                            uc4.metric(
                                "총 모집호수", f"{u_row['총 모집호수']} 호"
                            )
                            st.caption(
                                f"• 기본 임대조건: 보증금 {u_row['기본보증금']} / 월 임대료 {u_row['월임대료']}"
                            )
                        st.divider()

                    # 전체 주택형 배정표 출력
                    st.markdown("##### 📊 단지 전체 평형별 · 계층별 세부 배정표")
                    st.dataframe(
                        df_units, use_container_width=True, hide_index=True
                    )

                else:
                    st.warning(
                        f"이 공고는 '{target_row['주택유형']}' 유형입니다.\n"
                        "매입임대나 다가구 주택은 아파트식 단일 공급표가 없으며, 세부 호수 목록은 LH 공고문 원본(첨부파일)에 분산 기재되어 있습니다."
                    )

            # 2. LH 공식 상세 API 병행 호출 (공고문 PDF 직통 다운로드 및 일정 제공)
            with st.spinner("LH 공식 API에서 첨부 공고문 및 일정을 동기화 중..."):
                detail_json = fetch_lh_official_detail(
                    pan_id, ccr_cd, upp_cd, ais_cd, notice_title
                )
                if detail_json:
                    if "dsAhflInfo" in detail_json:
                        st.markdown("##### 📁 공식 첨부파일 (공고문 원본 PDF / HWP)")
                        ahfl_df = pd.DataFrame(detail_json["dsAhflInfo"])
                        for _, f_row in ahfl_df.iterrows():
                            f_name = f_row.get("CMN_AHFL_NM", "첨부파일")
                            f_url = f_row.get("AHFL_URL", "")
                            f_type = f_row.get("SL_PAN_AHFL_DS_CD_NM", "파일")
                            if f_url:
                                st.markdown(
                                    f"• **[{f_type}]** [{f_name}]({f_url})"
                                )

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
                        show_scdl = [
                            c for c in scdl_map.keys() if c in scdl_df.columns
                        ]
                        st.dataframe(
                            scdl_df[show_scdl].rename(columns=scdl_map),
                            use_container_width=True,
                            hide_index=True,
                        )

# ---------------------------------------------------------
# 탭 4: 상호전환보증금 계산기
# ---------------------------------------------------------
with tab4:
    st.subheader("💡 상호전환보증금(월 주거비) 시뮬레이션")
    s1, s2 = st.columns(2)
    with s1:
        base_dep = st.number_input("기본 보증금 (만원)", value=6000, step=100)
        base_rent = st.number_input("기본 월세 (원)", value=275000, step=10000)
    with s2:
        add_dep = st.slider(
            "추가 납부 전환보증금 (만원)",
            min_value=0,
            max_value=5000,
            value=3000,
            step=100,
        )
        loan_rate = (
            st.slider(
                "버팀목 대출 금리 (%)",
                min_value=1.5,
                max_value=3.5,
                value=2.1,
                step=0.1,
            )
            / 100.0
        )

    reduced_r = (add_dep * 10000) * (0.06 / 12)
    final_rent = max(base_rent - reduced_r, 0)
    monthly_interest = (add_dep * 10000) * (loan_rate / 12)
    total_expense = final_rent + monthly_interest

    res1, res2, res3 = st.columns(3)
    res1.metric("최종 전환보증금", f"{(base_dep + add_dep):,}만 원")
    res2.metric(
        "최종 월세",
        f"{int(final_rent):,}원",
        f"-{int(base_rent - final_rent):,}원 절감",
    )
    res3.metric(
        "예상 월 실부담금 (월세+이자)",
        f"{int(total_expense):,}원",
        f"기본 대비 매달 {int(base_rent - total_expense):,}원 절약",
    )
