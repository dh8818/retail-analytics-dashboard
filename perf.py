# -*- coding: utf-8 -*-
"""
会话内缓存：Streamlit 每次交互都会从头跑一遍脚本，
把「同一份数据 + 同样参数」算出来的重活存起来，手机上就不会一动一卡。

只存在当前浏览器会话里（st.session_state），不落盘、不跨用户。
"""
import streamlit as st


def set_sig(sig):
    """数据变了就清空缓存。"""
    if st.session_state.get("_cache_sig") != sig:
        st.session_state["_cache_sig"] = sig
        st.session_state["_memo"] = {}


def get(tag, fn):
    """按 tag 取缓存；没有就现算并存下来。"""
    memo = st.session_state.setdefault("_memo", {})
    if tag in memo:
        return memo[tag]
    val = fn()
    memo[tag] = val
    return val


def clear():
    st.session_state["_memo"] = {}


def size():
    return len(st.session_state.get("_memo", {}))
