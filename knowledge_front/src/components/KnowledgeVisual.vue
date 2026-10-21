<script setup lang="ts">
import { Document, ChatDotRound, Cpu, Connection } from "@element-plus/icons-vue";
</script>
<template>
  <div
    class="knowledge-visual"
    role="img"
    aria-label="文档知识通过智能知识引擎连接团队问答与机器人"
  >
    <div class="visual-grid" />
    <div class="orbit orbit-one" />
    <div class="orbit orbit-two" />
    <div class="orbit orbit-three" />
    <svg
      class="visual-connections"
      viewBox="0 0 640 560"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M132 140L320 280L532 140M100 365L320 280L520 420"
        stroke="#f68b00"
        stroke-opacity=".35"
        stroke-dasharray="4 8"
      />
      <path
        d="M320 55V135M320 425V510M75 280H175M465 280H570"
        stroke="#fff"
        stroke-opacity=".1"
      />
      <circle
        cx="320"
        cy="55"
        r="3"
        fill="#f68b00"
      />
      <circle
        cx="570"
        cy="280"
        r="3"
        fill="#f68b00"
      />
      <circle
        cx="320"
        cy="280"
        r="210"
        stroke="#fff"
        stroke-opacity=".06"
        stroke-dasharray="1 15"
      />
    </svg>
    <div class="knowledge-core">
      <div class="core-top">DEXFORCE</div>
      <el-icon :size="49"><Connection /></el-icon>
      <strong>知识引擎</strong>
      <span>CONNECT · UNDERSTAND · CREATE</span>
    </div>
    <div class="visual-node node-document">
      <el-icon><Document /></el-icon>
      <div>
        <b>文档知识</b>
        <span>从沉淀到连接</span>
      </div>
      <i />
    </div>
    <div class="visual-node node-chat">
      <el-icon><ChatDotRound /></el-icon>
      <div>
        <b>智能问答</b>
        <span>让知识随问即达</span>
      </div>
    </div>
    <div class="visual-node node-robot">
      <el-icon><Cpu /></el-icon>
      <div>
        <b>机器人接入</b>
        <span>赋予智能更多可能</span>
      </div>
      <i />
    </div>
    <div class="visual-caption">
      <span class="live-dot" />
      KNOWLEDGE IN MOTION
      <span>01 — ∞</span>
    </div>
  </div>
</template>
