"""
Trade Journal — Streamlit UI
Main entry point. Implements all 5 tabs:
  1. Needs Review  2. Trade Detail  3. History  4. Statistics  5. Settings
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))

from database import get_connection, init_db
import config as cfg
import backup as bkp

# ── Initialise ──
init_db()

st.set_page_config(page_title="TradeJournal", page_icon="📊", layout="wide", initial_sidebar_state="collapsed")

# ── Dark Theme CSS ──
st.markdown("""
<style>
.stApp { background-color: #0d1117; }
section[data-testid="stSidebar"] { background-color: #161b22; }
.stApp, .stApp p, .stApp label, .stApp span, .stMarkdown { color: #e6edf3 !important; }
h1, h2, h3, h4 { color: #e6edf3 !important; }
[data-testid="stMetric"] { background: #161b22; border: 0.5px solid #30363d; border-radius: 8px; padding: 12px 16px; }
[data-testid="stMetricLabel"] { color: #6e7681 !important; font-size: 12px !important; }
[data-testid="stMetricValue"] { font-size: 22px !important; }
.stTextInput input, .stTextArea textarea, .stSelectbox select,
.stNumberInput input, .stDateInput input {
    background-color: #1c2129 !important; color: #e6edf3 !important;
    border: 0.5px solid #30363d !important; border-radius: 6px !important; }
.stTabs [data-baseweb="tab-list"] { gap: 0; border-bottom: 1px solid #30363d; }
.stTabs [data-baseweb="tab"] { color: #8b949e; background: transparent; border-bottom: 2px solid transparent; padding: 8px 16px; }
.stTabs [aria-selected="true"] { color: #58a6ff !important; border-bottom-color: #58a6ff !important; }
.stButton > button { background: #1c2129; color: #e6edf3; border: 0.5px solid #30363d; border-radius: 6px; }
.stButton > button:hover { background: #1f2937; border-color: #58a6ff; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }
.badge-stock { background: rgba(88,166,255,.15); color: #58a6ff; }
.badge-option { background: rgba(188,140,255,.15); color: #bc8cff; }
.badge-spread { background: rgba(210,153,34,.15); color: #d29922; }
.badge-long { background: rgba(63,185,80,.15); color: #3fb950; }
.badge-short { background: rgba(248,81,73,.15); color: #f85149; }
.badge-pending { background: rgba(88,166,255,.15); color: #58a6ff; }
.badge-reviewed { background: rgba(63,185,80,.1); color: #3fb950; }
.acct-tag { font-size: 12px; color: #3ddbd9; background: rgba(61,219,217,.12); padding: 2px 6px; border-radius: 3px; }
.pnl-pos { color: #3fb950; } .pnl-neg { color: #f85149; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ──
def get_accounts():
    conn = get_connection()
    accts = conn.execute("SELECT * FROM accounts ORDER BY broker_account_id").fetchall()
    conn.close()
    return [dict(a) for a in accts]

def get_setup_types():
    conn = get_connection()
    types = conn.execute("SELECT name FROM setup_types ORDER BY name").fetchall()
    conn.close()
    return [t["name"] for t in types]

def badge(text, cls):
    return f'<span class="badge badge-{cls}">{text}</span>'

def pnl_html(val):
    if val is None: return "-"
    cls = "pnl-pos" if val >= 0 else "pnl-neg"
    sign = "+" if val >= 0 else ""
    return f'<span class="{cls}">{sign}${val:,.2f}</span>'

def tradingview_embed(symbol, height=400):
    clean = symbol.split(" ")[0] if " " in symbol else symbol
    html = f'''<div style="height:{height}px">
    <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js">
    {{"autosize": true, "symbol": "{clean}", "interval": "D", "timezone": "America/New_York",
     "theme": "dark", "style": "1", "locale": "en", "hide_side_toolbar": false,
     "allow_symbol_change": true, "save_image": false}}
    </script></div>'''
    st.components.v1.html(html, height=height + 20)

type_map = {"Stock": "stock", "Single option": "option", "Spread": "spread"}


# ── Title ──
st.markdown('<span style="font-size:20px;font-weight:500;color:#58a6ff">TradeJournal</span> <span style="color:#6e7681;font-size:12px">v1.2</span>', unsafe_allow_html=True)

# ── Tabs ──
tabs = st.tabs(["Needs review", "Trade detail", "History", "Statistics", "Settings"])


# ═══ TAB 1: NEEDS REVIEW ═══
with tabs[0]:
    conn = get_connection()
    accounts = get_accounts()

    # Summary metrics
    pending = conn.execute("SELECT COUNT(*) as c FROM trades WHERE review_status = 'pending'").fetchone()["c"]
    today = datetime.now().strftime("%Y-%m-%d")
    today_imports = conn.execute("SELECT COUNT(*) as c FROM imports WHERE date(import_started_at) = ?", (today,)).fetchone()["c"]
    today_pnl = conn.execute("SELECT COALESCE(SUM(net_pnl), 0) as s FROM trades WHERE date(exit_datetime) = ?", (today,)).fetchone()["s"]
    last_import = conn.execute("SELECT import_finished_at FROM imports WHERE status='success' ORDER BY import_finished_at DESC LIMIT 1").fetchone()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Awaiting review", pending)
    c2.metric("Today's imports", today_imports)
    c3.metric("Today's P&L", f"{'+'if today_pnl>=0 else ''}${today_pnl:,.2f}")
    c4.metric("Last import", last_import["import_finished_at"][:16] if last_import else "Never")

    # Filters
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        acct_opts = ["All accounts"] + [f"{a['broker_account_id']} ({a['alias'] or a['broker_account_id']})" for a in accounts]
        sel_acct = st.selectbox("Account", acct_opts, key="nr_acct")
    with fc2:
        sel_type = st.selectbox("Type", ["All types", "Stock", "Single option", "Spread"], key="nr_type")
    with fc3:
        sel_setup = st.selectbox("Setup type", ["All setup types"] + get_setup_types(), key="nr_setup")

    # Build query
    where = ["1=1"]
    params = []
    if sel_acct != "All accounts":
        where.append("t.broker_account_id = ?")
        params.append(sel_acct.split(" (")[0])
    if sel_type != "All types":
        where.append("t.trade_type = ?")
        params.append(type_map[sel_type])
    if sel_setup != "All setup types":
        where.append("(t.setup_type = ? OR r.setup_type = ?)")
        params.extend([sel_setup, sel_setup])

    trades_list = conn.execute(f"""
        SELECT t.*, r.setup_class FROM trades t
        LEFT JOIN trade_reviews r ON t.id = r.trade_id
        WHERE {' AND '.join(where)}
        ORDER BY t.entry_datetime DESC LIMIT 50
    """, params).fetchall()

    for t in trades_list:
        t = dict(t)
        cols = st.columns([1, 2, 1, 1, 1, 1, 1, 1, 1])
        cols[0].markdown(f'<span class="acct-tag">{t.get("broker_account_name") or t["broker_account_id"][:6]}</span>', unsafe_allow_html=True)
        cols[1].write(f"**{t['symbol']}**")
        cols[2].markdown(badge(t["trade_type"], t["trade_type"]), unsafe_allow_html=True)
        cols[3].markdown(badge(t["direction"], "long" if t["direction"] in ("long","debit") else "short"), unsafe_allow_html=True)
        cols[4].write(f"${t['entry_price_avg']:.2f}" if t["entry_price_avg"] else "-")
        cols[5].write(f"${t['exit_price_avg']:.2f}" if t["exit_price_avg"] else "-")
        cols[6].markdown(pnl_html(t["net_pnl"]), unsafe_allow_html=True)
        cols[7].write(t.get("setup_class") or "-")
        status_cls = "reviewed" if t["review_status"] == "reviewed" else "pending"
        cols[8].markdown(badge(t["review_status"], status_cls), unsafe_allow_html=True)

    conn.close()


# ═══ TAB 2: TRADE DETAIL ═══
with tabs[1]:
    conn = get_connection()
    all_trades = conn.execute("""
        SELECT t.*, r.setup_class FROM trades t
        LEFT JOIN trade_reviews r ON t.id = r.trade_id
        ORDER BY t.entry_datetime DESC
    """).fetchall()

    if not all_trades:
        st.info("No trades yet. Import data in Settings tab.")
    else:
        options = [f"{t['symbol']} | {t['trade_type']} | {pnl_html(t['net_pnl']).replace('<span class=\"pnl-pos\">','').replace('<span class=\"pnl-neg\">','').replace('</span>','')} | {(t['entry_datetime'] or '')[:10]}" for t in all_trades]
        sel_idx = st.selectbox("Select trade", range(len(options)), format_func=lambda i: options[i], key="td_sel")
        trade = dict(all_trades[sel_idx])
        trade_id = trade["id"]

        # Summary
        st.markdown(f"### {trade['symbol']}")
        st.markdown(f"{badge(trade['trade_type'], trade['trade_type'])} {badge(trade['direction'], 'long' if trade['direction'] in ('long','debit') else 'short')} {badge(trade['review_status'], 'reviewed' if trade['review_status']=='reviewed' else 'pending')}", unsafe_allow_html=True)

        dc = st.columns(4)
        dc[0].metric("Entry", f"${trade['entry_price_avg']:.2f}" if trade["entry_price_avg"] else "-")
        dc[1].metric("Exit", f"${trade['exit_price_avg']:.2f}" if trade["exit_price_avg"] else "-")
        dc[2].metric("Net P&L", f"{'+'if (trade['net_pnl'] or 0)>=0 else ''}${(trade['net_pnl'] or 0):,.2f}")
        dc[3].metric("Holding", f"{trade['holding_minutes'] or 0}m")

        # TradingView chart
        st.markdown("---")
        st.caption(f"TradingView chart — {trade['underlying_symbol'] or trade['symbol']}")
        tradingview_embed(trade["underlying_symbol"] or trade["symbol"])

        if trade["entry_price_avg"]:
            st.markdown(f'🟢 Entry: ${trade["entry_price_avg"]:.2f} @ {(trade["entry_datetime"] or "")[:16]}')
        if trade["exit_price_avg"]:
            st.markdown(f'🔴 Exit: ${trade["exit_price_avg"]:.2f} @ {(trade["exit_datetime"] or "")[:16]}')

        # Review form
        st.markdown("---")
        st.subheader("Manual review")

        existing_review = conn.execute("SELECT * FROM trade_reviews WHERE trade_id = ?", (trade_id,)).fetchone()
        er = dict(existing_review) if existing_review else {}

        note_tab, mental_tab, outcome_tab = st.tabs(["Notes", "Mental state", "Outcome"])

        with note_tab:
            nc1, nc2 = st.columns(2)
            with nc1:
                setup_class = st.selectbox("Setup class", ["", "A+", "A", "B", "C", "F"], index=["", "A+", "A", "B", "C", "F"].index(er.get("setup_class", "") or ""), key="rv_class")
            with nc2:
                setup_types_list = get_setup_types()
                setup_type = st.selectbox("Setup type", [""] + setup_types_list, index=([""] + setup_types_list).index(er.get("setup_type", "") or "") if er.get("setup_type", "") in [""] + setup_types_list else 0, key="rv_setup")

            tags = st.text_input("Tags", value=er.get("manual_tags_json", "") or "", key="rv_tags", placeholder="e.g. momentum, earnings, gap-up")
            comment = st.text_area("Comment", value=er.get("comment", "") or "", key="rv_comment")
            qqq_note = st.text_input("QQQ EMA note", value=er.get("qqq_ema_note", "") or "", key="rv_qqq")
            sym_note = st.text_input("Symbol EMA note", value=er.get("symbol_ema_note", "") or "", key="rv_sym")
            tq_note = st.text_input("TQ/TICKQ note", value=er.get("tq_tickq_note", "") or "", key="rv_tq")

        with mental_tab:
            emotion_opts = ["calm", "focused", "fearful", "FOMO", "impatient"]
            saved_emotions = json.loads(er.get("emotion_json", "[]") or "[]")
            emotions = st.multiselect("Emotion at entry", emotion_opts, default=[e for e in saved_emotions if e in emotion_opts], key="rv_emo")
            confidence = st.slider("Confidence rating", 0, 5, er.get("confidence_rating", 0) or 0, key="rv_conf")
            regime = st.text_input("Market regime note", value=er.get("market_regime_note", "") or "", key="rv_regime")

        with outcome_tab:
            exec_score = st.slider("Execution score", 0, 5, er.get("execution_score", 0) or 0, key="rv_exec")
            wta_opts = ["", "yes", "no", "with_changes"]
            would_take = st.selectbox("Would take again?", wta_opts, index=wta_opts.index(er.get("would_take_again", "") or ""), key="rv_wta")
            lesson = st.text_area("Lesson learned", value=er.get("lesson_learned", "") or "", key="rv_lesson")
            mistake = st.text_area("Mistake narrative", value=er.get("mistake_narrative", "") or "", key="rv_mistake")

        if st.button("Save review", type="primary", key="rv_save"):
            conn2 = get_connection()
            conn2.execute("""
                INSERT INTO trade_reviews (
                    trade_id, setup_class, setup_type, manual_tags_json, comment,
                    emotion_json, lesson_learned, execution_score, market_regime_note,
                    confidence_rating, mistake_narrative, would_take_again,
                    qqq_ema_note, symbol_ema_note, tq_tickq_note, reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(trade_id) DO UPDATE SET
                    setup_class=excluded.setup_class, setup_type=excluded.setup_type,
                    manual_tags_json=excluded.manual_tags_json, comment=excluded.comment,
                    emotion_json=excluded.emotion_json, lesson_learned=excluded.lesson_learned,
                    execution_score=excluded.execution_score, market_regime_note=excluded.market_regime_note,
                    confidence_rating=excluded.confidence_rating, mistake_narrative=excluded.mistake_narrative,
                    would_take_again=excluded.would_take_again, qqq_ema_note=excluded.qqq_ema_note,
                    symbol_ema_note=excluded.symbol_ema_note, tq_tickq_note=excluded.tq_tickq_note,
                    reviewed_at=datetime('now')
            """, (trade_id, setup_class or None, setup_type or None, tags or None, comment or None,
                  json.dumps(emotions) if emotions else None, lesson or None, exec_score or None,
                  regime or None, confidence or None, mistake or None, would_take or None,
                  qqq_note or None, sym_note or None, tq_note or None))

            conn2.execute("UPDATE trades SET review_status = 'reviewed', setup_type = ?, updated_at = datetime('now') WHERE id = ?",
                          (setup_type if setup_type else None, trade_id))
            conn2.commit()
            conn2.close()
            st.success("Review saved!")
            st.rerun()

    conn.close()


# ═══ TAB 3: HISTORY ═══
with tabs[2]:
    conn = get_connection()
    hc1, hc2, hc3, hc4 = st.columns(4)
    with hc1:
        h_from = st.date_input("From", value=datetime.now().date() - timedelta(days=30), key="h_from")
    with hc2:
        h_to = st.date_input("To", value=datetime.now().date(), key="h_to")
    with hc3:
        h_type = st.selectbox("Type", ["All types", "Stock", "Single option", "Spread"], key="h_type")
    with hc4:
        h_status = st.selectbox("Status", ["All", "Reviewed", "Needs review"], key="h_status")

    where_h = ["date(t.entry_datetime) >= ?", "date(t.entry_datetime) <= ?"]
    params_h = [str(h_from), str(h_to)]

    if h_type != "All types":
        where_h.append("t.trade_type = ?")
        params_h.append(type_map[h_type])
    if h_status == "Reviewed":
        where_h.append("t.review_status = 'reviewed'")
    elif h_status == "Needs review":
        where_h.append("t.review_status = 'pending'")

    history = conn.execute(f"""
        SELECT t.*, r.setup_class FROM trades t
        LEFT JOIN trade_reviews r ON t.id = r.trade_id
        WHERE {' AND '.join(where_h)}
        ORDER BY t.entry_datetime DESC
    """, params_h).fetchall()

    if history:
        for t in history:
            t = dict(t)
            cols = st.columns([1, 1, 2, 1, 1, 1, 1, 1])
            cols[0].write((t["entry_datetime"] or "")[:10])
            cols[1].markdown(f'<span class="acct-tag">{t.get("broker_account_name") or t["broker_account_id"][:6]}</span>', unsafe_allow_html=True)
            cols[2].write(f"**{t['symbol']}**")
            cols[3].markdown(badge(t["trade_type"], t["trade_type"]), unsafe_allow_html=True)
            cols[4].markdown(badge(t["direction"], "long" if t["direction"] in ("long","debit") else "short"), unsafe_allow_html=True)
            cols[5].markdown(pnl_html(t["net_pnl"]), unsafe_allow_html=True)
            cols[6].write(t.get("setup_class") or "-")
            cols[7].markdown(badge(t["review_status"], "reviewed" if t["review_status"]=="reviewed" else "pending"), unsafe_allow_html=True)
    else:
        st.info("No trades found for the selected filters.")
    conn.close()


# ═══ TAB 4: STATISTICS ═══
with tabs[3]:
    conn = get_connection()
    stats = conn.execute("SELECT * FROM trades WHERE status = 'closed'").fetchall()

    if not stats:
        st.info("No closed trades yet.")
    else:
        total = len(stats)
        winners = [t for t in stats if (t["net_pnl"] or 0) > 0]
        losers = [t for t in stats if (t["net_pnl"] or 0) <= 0]
        win_rate = len(winners) / total * 100 if total else 0
        avg_win = sum(t["net_pnl"] for t in winners) / len(winners) if winners else 0
        avg_loss = sum(t["net_pnl"] for t in losers) / len(losers) if losers else 0
        total_pnl = sum(t["net_pnl"] or 0 for t in stats)

        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("Total trades", total)
        sc2.metric("Win rate", f"{win_rate:.0f}%")
        sc3.metric("Avg winner", f"+${avg_win:,.2f}")
        sc4.metric("Avg loser", f"${avg_loss:,.2f}")

        sc5, sc6, sc7, sc8 = st.columns(4)
        sc5.metric("Net P&L", f"{'+'if total_pnl>=0 else ''}${total_pnl:,.2f}")
        gross_win = sum(t["net_pnl"] for t in winners)
        gross_loss = abs(sum(t["net_pnl"] for t in losers)) if losers else 1
        sc6.metric("Profit factor", f"{gross_win/gross_loss:.2f}" if gross_loss else "∞")
        if stats:
            best = max(t["net_pnl"] or 0 for t in stats)
            worst = min(t["net_pnl"] or 0 for t in stats)
            sc7.metric("Best trade", f"+${best:,.2f}")
            sc8.metric("Worst trade", f"${worst:,.2f}")

        # Breakdown by type
        st.markdown("---")
        bc1, bc2 = st.columns(2)
        with bc1:
            st.caption("BY TRADE TYPE")
            for tt in ["stock", "option", "spread"]:
                tt_trades = [t for t in stats if t["trade_type"] == tt]
                if tt_trades:
                    tt_wins = len([t for t in tt_trades if (t["net_pnl"] or 0) > 0])
                    tt_pnl = sum(t["net_pnl"] or 0 for t in tt_trades)
                    st.write(f"**{tt.title()}**: {len(tt_trades)} trades | {tt_wins/len(tt_trades)*100:.0f}% win | {pnl_html(tt_pnl)}", unsafe_allow_html=True)

        with bc2:
            st.caption("BY SETUP TYPE")
            setup_types_used = set()
            for t in stats:
                if t.get("setup_type"):
                    setup_types_used.add(t["setup_type"])
            for su in sorted(setup_types_used):
                su_trades = [t for t in stats if t.get("setup_type") == su]
                if su_trades:
                    su_wins = len([t for t in su_trades if (t["net_pnl"] or 0) > 0])
                    su_pnl = sum(t["net_pnl"] or 0 for t in su_trades)
                    st.write(f"**{su}**: {len(su_trades)} trades | {su_wins/len(su_trades)*100:.0f}% win | {pnl_html(su_pnl)}", unsafe_allow_html=True)

    conn.close()


# ═══ TAB 5: SETTINGS ═══
with tabs[4]:
    config = cfg.load_config()

    st.subheader("IBKR Connection")
    sc1, sc2 = st.columns(2)
    with sc1:
        token = st.text_input("Flex token", value=config.get("ibkr_token", ""), type="password", key="s_token")
    with sc2:
        query_id = st.text_input("Query ID", value=config.get("ibkr_query_id", ""), key="s_qid")

    if st.button("Save settings", key="s_save"):
        cfg.save_config({**config, "ibkr_token": token, "ibkr_query_id": query_id})
        st.success("Settings saved!")

    st.markdown("---")
    st.subheader("Import")

    ic1, ic2 = st.columns(2)
    with ic1:
        if st.button("Run import now", key="s_import"):
            from importer import run_import
            from reconstruction import reconstruct_all_new
            result = run_import(token=config.get("ibkr_token", ""), query_id=config.get("ibkr_query_id", ""))
            st.write(result)
            if result["status"] == "success":
                recon = reconstruct_all_new()
                st.write(recon)
    with ic2:
        uploaded = st.file_uploader("Upload Flex XML", type=["xml"], key="s_upload")
        if uploaded:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xml")
            tmp.write(uploaded.read())
            tmp.close()
            from importer import import_from_file
            from reconstruction import reconstruct_all_new
            result = import_from_file(tmp.name)
            st.write(result)
            if result["status"] == "success":
                recon = reconstruct_all_new()
                st.write(recon)
            os.unlink(tmp.name)

    st.markdown("---")
    st.subheader("Setup types")
    current_types = get_setup_types()
    st.write(", ".join(current_types) if current_types else "None configured")
    nc1, nc2 = st.columns([3, 1])
    with nc1:
        new_type = st.text_input("New setup type", key="s_new_type")
    with nc2:
        st.write("")
        st.write("")
        if st.button("+ Add", key="s_add_type") and new_type:
            conn = get_connection()
            conn.execute("INSERT OR IGNORE INTO setup_types (name) VALUES (?)", (new_type,))
            conn.commit()
            conn.close()
            st.rerun()

    st.markdown("---")
    st.subheader("Backup & Export")
    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        if st.button("Backup database", key="s_backup"):
            path = bkp.backup_database()
            st.success(f"Backed up to {path}")
    with bc2:
        if st.button("Export CSV", key="s_csv"):
            csv_data = bkp.export_trades_csv()
            if csv_data:
                st.download_button("Download CSV", csv_data, "trades_export.csv", "text/csv")
            else:
                st.info("No trades to export")
    with bc3:
        if st.button("Export SQLite", key="s_sqlite"):
            db_path = bkp.get_database_path()
            if os.path.exists(db_path):
                with open(db_path, "rb") as f:
                    st.download_button("Download DB", f.read(), "trade_journal.db", "application/octet-stream")
