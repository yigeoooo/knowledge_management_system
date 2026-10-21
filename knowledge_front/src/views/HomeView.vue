<script setup lang="ts">
import { ref } from "vue";
import {
  ArrowRight,
  ArrowDown,
  Document,
  ChatDotRound,
  Cpu,
  Lock,
  Menu,
  Close,
  TopRight,
} from "@element-plus/icons-vue";
import BrandLogo from "../components/BrandLogo.vue";
import KnowledgeVisual from "../components/KnowledgeVisual.vue";
const menuOpen = ref(false);
const features = [
  {
    icon: Document,
    number: "01",
    title: "让知识，有序沉淀",
    text: "将产品手册、技术文档与团队经验汇聚一处，构建清晰、可持续更新的知识空间。",
    tag: "知识库管理",
  },
  {
    icon: ChatDotRound,
    number: "02",
    title: "让答案，有据可循",
    text: "用自然语言探索知识，从问题直达答案。结合文档来源，让每一次回答都可追溯。",
    tag: "智能知识问答",
  },
  {
    icon: Cpu,
    number: "03",
    title: "让智能，走向现场",
    text: "连接机器人与业务知识，让设备理解场景，让积累的经验在真实世界发挥价值。",
    tag: "机器人知识服务",
  },
];
const steps = [
  ["汇聚知识", "统一归集 Markdown 文档，构建专属知识库。"],
  ["理解内容", "解析文档、构建索引，让知识可以被理解与检索。"],
  ["连接场景", "通过网页问答与机器人服务，将知识应用到现场。"],
];
</script>
<template>
  <div class="landing">
    <a
      class="skip-link"
      href="#main-content"
    >
      跳转到主要内容
    </a>
    <header class="site-header">
      <div class="wide-container header-inner">
        <BrandLogo />
        <nav
          class="desktop-nav"
          aria-label="主导航"
        >
          <RouterLink
            class="active"
            to="/"
          >
            首页
          </RouterLink>
          <a href="#capabilities">平台能力</a>
          <a href="#workflow">工作流程</a>
          <a href="#scenarios">应用场景</a>
        </nav>
        <div class="header-actions">
          <el-button
            type="primary"
            @click="$router.push('/login')"
          >
            登录平台
            <el-icon><ArrowRight /></el-icon>
          </el-button>
          <el-button
            class="mobile-menu"
            text
            :aria-expanded="menuOpen"
            aria-label="切换导航菜单"
            @click="menuOpen = !menuOpen"
          >
            <el-icon>
              <Close v-if="menuOpen" />
              <Menu v-else />
            </el-icon>
          </el-button>
        </div>
      </div>
      <nav
        v-if="menuOpen"
        class="mobile-nav"
        aria-label="移动导航"
        @click="menuOpen = false"
      >
        <a href="#capabilities">平台能力</a>
        <a href="#workflow">工作流程</a>
        <a href="#scenarios">应用场景</a>
      </nav>
    </header>
    <main id="main-content">
      <section class="hero wide-container">
        <div class="hero-copy">
          <div class="eyebrow">
            <span class="tiny-square" />
            DEXFORCE KNOWLEDGE HUB
          </div>
          <h1>
            连接每一份知识
            <br />
            释放
            <span>智能的力量</span>
          </h1>
          <p class="hero-description">
            从文档到答案，从团队到机器人。
            <br />
            构建统一的知识底座，让经验沉淀，让智能生长。
          </p>
          <div class="hero-actions">
            <el-button
              type="primary"
              size="large"
              @click="$router.push('/login')"
            >
              进入知识平台
              <el-icon><ArrowRight /></el-icon>
            </el-button>
            <a
              class="text-action"
              href="#capabilities"
            >
              探索平台能力
              <el-icon><TopRight /></el-icon>
            </a>
          </div>
          <div class="hero-note">
            <el-icon><Lock /></el-icon>
            企业知识 · 安全连接 · 协同共享
          </div>
        </div>
        <KnowledgeVisual />
        <a
          class="scroll-cue"
          href="#capabilities"
        >
          <span>向下探索</span>
          <el-icon><ArrowDown /></el-icon>
        </a>
      </section>
      <div class="platform-strip">
        <div class="wide-container strip-inner">
          <span class="strip-title">为知识赋予行动力</span>
          <span>
            <Document />
            知识沉淀
          </span>
          <i />
          <span>
            <ChatDotRound />
            可信问答
          </span>
          <i />
          <span>
            <Cpu />
            机器人连接
          </span>
          <i />
          <span>
            <Lock />
            权限管理
          </span>
        </div>
      </div>
      <section
        id="capabilities"
        class="section wide-container"
      >
        <div class="section-heading">
          <div>
            <div class="eyebrow">PLATFORM CAPABILITIES</div>
            <h2>知识的价值，不止于存储</h2>
          </div>
          <p>
            从内容管理到场景应用
            <br />
            连接人与知识的每一个环节
          </p>
        </div>
        <div class="feature-grid">
          <el-card
            v-for="feature in features"
            :key="feature.number"
            class="feature-card"
            shadow="never"
          >
            <div class="feature-top">
              <el-icon><component :is="feature.icon" /></el-icon>
              <span>{{ feature.number }}</span>
            </div>
            <h3>{{ feature.title }}</h3>
            <p>{{ feature.text }}</p>
            <div class="feature-bottom">
              <span>{{ feature.tag }}</span>
              <el-icon><TopRight /></el-icon>
            </div>
          </el-card>
        </div>
      </section>
      <section
        id="workflow"
        class="workflow-section"
      >
        <div class="wide-container section">
          <div class="section-heading">
            <div>
              <div class="eyebrow">HOW IT WORKS</div>
              <h2>让知识，流动起来</h2>
            </div>
            <span class="section-counter">01 / 03</span>
          </div>
          <div class="steps">
            <article
              v-for="(step, index) in steps"
              :key="step[0]"
            >
              <div class="step-number">
                0{{ index + 1 }}
                <span />
              </div>
              <h3>{{ step[0] }}</h3>
              <p>{{ step[1] }}</p>
            </article>
          </div>
        </div>
      </section>
      <section
        id="scenarios"
        class="section wide-container"
      >
        <div class="section-heading">
          <div>
            <div class="eyebrow">BUILT FOR YOUR TEAM</div>
            <h2>同一份知识，更多种可能</h2>
          </div>
        </div>
        <div class="scenario-grid">
          <article>
            <span class="scenario-label">FOR PEOPLE</span>
            <h3>让团队，专注于创造</h3>
            <p>
              产品查询、技术支持、经验共享。
              <br />
              把寻找答案的时间，留给更有价值的工作。
            </p>
            <el-button
              plain
              @click="$router.push('/login?redirect=/qa')"
            >
              探索知识问答
              <el-icon><ArrowRight /></el-icon>
            </el-button>
          </article>
          <article>
            <span class="scenario-label">FOR ROBOTS</span>
            <h3>让机器人，理解更多</h3>
            <p>
              打通知识与设备之间的连接。
              <br />
              用持续更新的业务知识，支持每一个服务场景。
            </p>
            <div
              class="scenario-symbol"
              aria-hidden="true"
            >
              <Cpu />
            </div>
          </article>
        </div>
      </section>
      <section class="landing-cta">
        <div class="wide-container">
          <div>
            <div class="eyebrow">KNOWLEDGE POWERS POSSIBILITY</div>
            <h2>下一次突破，从连接知识开始。</h2>
          </div>
          <el-button
            type="primary"
            size="large"
            @click="$router.push('/login')"
          >
            开启知识之旅
            <el-icon><ArrowRight /></el-icon>
          </el-button>
        </div>
      </section>
    </main>
    <footer class="site-footer wide-container">
      <div>
        <BrandLogo compact />
        <p>连接知识，迈向智能。</p>
      </div>
      <div class="footer-right">
        <a
          href="https://www.dexforce.com/"
          target="_blank"
          rel="noopener noreferrer"
        >
          跨维智能官网
          <el-icon><TopRight /></el-icon>
        </a>
        <span>© {{ new Date().getFullYear() }} DEXFORCE 跨维智能</span>
      </div>
    </footer>
  </div>
</template>
