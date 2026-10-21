<script setup lang="ts">
import { reactive, ref } from "vue";
import type { FormInstance, FormRules } from "element-plus";
import { ArrowLeft, ArrowRight, Lock, User, InfoFilled } from "@element-plus/icons-vue";
import { useRoute, useRouter } from "vue-router";
import BrandLogo from "../components/BrandLogo.vue";
import KnowledgeVisual from "../components/KnowledgeVisual.vue";
import { login } from "../lib/session";
import { installPages, loginDestination } from "../router";
const route = useRoute(),
  router = useRouter();
const formRef = ref<FormInstance>(),
  busy = ref(false),
  error = ref(""),
  help = ref(false);
const form = reactive({ username: "", password: "" });
const rules: FormRules = {
  username: [{ required: true, whitespace: true, message: "请输入用户名", trigger: "blur" }],
  password: [{ required: true, message: "请输入密码", trigger: "blur" }],
};
async function submit() {
  if (busy.value || !(await formRef.value?.validate().catch(() => false))) return;
  busy.value = true;
  error.value = "";
  try {
    await login(form.username.trim(), form.password);
    form.password = "";
    installPages();
    await router.replace(loginDestination(route.query.redirect));
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <main class="login-page">
    <section class="login-brand-panel">
      <BrandLogo />
      <div class="login-story">
        <div class="eyebrow">KNOWLEDGE MEETS POSSIBILITY</div>
        <h1>
          每一份知识
          <br />
          都蕴藏
          <span>新的可能</span>
        </h1>
        <p>连接团队智慧，驱动智能生长。</p>
        <KnowledgeVisual />
      </div>
      <span class="login-copyright">© {{ new Date().getFullYear() }} DEXFORCE 跨维智能</span>
    </section>
    <section class="login-form-panel">
      <RouterLink
        to="/"
        class="back-link"
      >
        <el-icon><ArrowLeft /></el-icon>
        返回首页
      </RouterLink>
      <div class="login-form-wrap">
        <div class="login-kicker">WELCOME TO DEXFORCE</div>
        <h2>欢迎回来</h2>
        <p class="login-subtitle">登录知识平台，继续探索与创造。</p>
        <el-alert
          v-if="error"
          :title="error"
          type="error"
          :closable="false"
          show-icon
          class="login-error"
          role="alert"
        />
        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          size="large"
          @submit.prevent="submit"
        >
          <el-form-item
            label="用户名"
            prop="username"
          >
            <el-input
              v-model="form.username"
              name="username"
              autocomplete="username"
              placeholder="请输入用户名"
              :prefix-icon="User"
              maxlength="100"
            />
          </el-form-item>
          <el-form-item
            label="密码"
            prop="password"
          >
            <el-input
              v-model="form.password"
              name="password"
              type="password"
              autocomplete="current-password"
              placeholder="请输入登录密码"
              :prefix-icon="Lock"
              show-password
              maxlength="1024"
            />
          </el-form-item>
          <div class="login-help">
            <span>
              <el-icon><Lock /></el-icon>
              安全登录
            </span>
            <el-button
              text
              @click="help = true"
            >
              忘记密码？
            </el-button>
          </div>
          <el-button
            class="login-submit"
            native-type="submit"
            type="primary"
            :loading="busy"
          >
            {{ busy ? "正在登录" : "登录平台" }}
            <el-icon v-if="!busy"><ArrowRight /></el-icon>
          </el-button>
        </el-form>
        <div class="account-note">
          <el-icon><InfoFilled /></el-icon>
          <span>账号由管理员统一分配。如需开通，请联系管理员。</span>
        </div>
      </div>
      <div class="login-bottom">
        DEXFORCE KNOWLEDGE HUB
        <span>知识，让智能更进一步。</span>
      </div>
    </section>
    <el-dialog
      v-model="help"
      title="找回账号或密码"
      width="420px"
      align-center
    >
      <p>请联系平台管理员核验身份并重置密码。平台暂不开放自主注册。</p>
      <template #footer>
        <el-button
          type="primary"
          @click="help = false"
        >
          我知道了
        </el-button>
      </template>
    </el-dialog>
  </main>
</template>
