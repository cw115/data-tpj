# python -m streamlit run app.py

import streamlit as st
import pandas as pd
import time

# 기본 화면 ----
st.set_page_config(
    page_title="TCP 혼잡 제어 시뮬레이터",
    layout="wide"
)

st.title("TCP 혼잡 제어 시뮬레이터")
st.write("TCP Tahoe / Reno 혼잡 제어 동작 시각화")


# 시뮬레이션 설정 UI ----
st.subheader("시뮬레이션 설정")

algorithm = st.selectbox(
    "TCP 알고리즘 선택",
    ["Tahoe", "Reno"]
)

loss_rate = st.slider(
    "패킷 손실률 (%)",
    min_value=0,
    max_value=20,
    value=5
)

rtt = st.number_input(
    "RTT (ms)",
    min_value=1,
    value=100
)


# (수정) Cwnd 그래프 테스트용 임시 데이터 삭제 후 알고리즘 연동
from tcp_algorithm import generate_simulation_data


# 시뮬레이션 실행 및 결과 표시 ----
if st.button("시뮬레이션 실행"):
    st.success("시뮬레이션 설정 완료!")
    st.write("알고리즘:", algorithm)
    st.write("패킷 손실률:", loss_rate, "%")
    st.write("RTT:", rtt, "ms")
    
# (추가) 버튼을 누를 때 선택한 옵션값으로 시뮬레이션 데이터를 생성
    data = generate_simulation_data(
        algorithm=algorithm, 
        loss_rate=loss_rate, 
        total_rounds=20
    )

    # Cwnd 실시간 그래프
    st.subheader("Cwnd 변화 그래프")
    chart = st.empty()

    for i in range(len(data)):
        current_data = data.iloc[:i+1]

# (수정) cwnd열만 출력되도록 지
        chart.line_chart(
            current_data.set_index("Round")[["Cwnd"]],
            x_label="Round",
            y_label="Cwnd (MSS)"
        )

        time.sleep(0.5)
