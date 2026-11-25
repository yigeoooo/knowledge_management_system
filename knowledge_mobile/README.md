# 跨维知识 App

Android 和 iOS 共用 Vue 3 手机界面，通过 Capacitor 安装到手机。项目位于 `knowledge_mobile/`，构建时从同一仓库的 `knowledge_front/` 复用会话 API、消息展示组件、基础样式和品牌素材。手机页面与 Vant 交互在 `knowledge_mobile/src/` 中维护。下列命令在 macOS 或 Linux 终端运行，除特别说明外，工作目录均为 `knowledge_mobile/`。

## 本地启动

从仓库根目录开始，使用 Node.js 22.12 或更高版本。

```bash
cd knowledge_mobile
npm ci
npm run dev
```

浏览器打开 <http://127.0.0.1:5180>。可用 Chrome 开发者工具的设备模式切换到竖屏。页面热更新，无需为每次样式调整重新打包。

登录和业务操作需要后端。浏览器开发模式把 `/api` 代理到 **电脑的 `127.0.0.1:5000`**。已初始化本地数据库和服务配置的开发者，可从仓库根目录在第二个终端启动后端：

```bash
cd knowledge_back
.venv/bin/flask --app app run --host 127.0.0.1 --port 5000
```

首次搭建后端，请先完成[开发环境配置](../knowledge_back/docs/development-environment.md)。在同一 Wi-Fi 的手机浏览器预览，可执行 `npm run dev -- --host 0.0.0.0`，在手机打开 `http://电脑局域网IP:5180`。此模式仍通过电脑代理请求后端。

## 运行测试

```bash
npm run build
npm test
```

第一条命令检查 TypeScript 并输出 `dist/`。第二条命令构建生产界面并自动启动预览服务，在手机尺寸的 Chrome 中测试两种角色、历史恢复、日志详情和排除的路由。测试使用模拟接口，无需后端账号。若机器未安装 Chrome，先执行 `npx playwright install chrome`。

## Android APK

安装 JDK 21、Android SDK Platform 36、Build Tools 和 Platform Tools，将 `ANDROID_HOME` 指向 Android SDK 目录。首次编译需要联网下载 Gradle 和依赖。

```bash
npm run android:debug
adb devices
adb install -r android/app/build/outputs/apk/debug/app-debug.apk
```

**可直接安装的调试 APK** 位于 `android/app/build/outputs/apk/debug/app-debug.apk`。也可以把 APK 传到安卓手机，点击文件安装。USB 安装需要手机开启 USB 调试并授权电脑。

安卓和 iOS 安装包均固定请求 `http://8.156.42.130:5000/api/v1`，登录时直接输入账号密码。手机必须能连通该地址的 5000 端口。该入口使用 HTTP，登录与业务流量未经 TLS 加密。本地浏览器预览继续使用电脑的本地后端。

正式 Android 分发使用团队发布密钥。先执行 `npm run sync`、`npx cap open android`，在 Android Studio 的 **Build → Generate Signed App Bundle or APK** 中选择 APK 或 AAB、发布密钥和 release。产物位置以向导指定目录为准。请保留签名密钥供后续升级使用。

## iPhone 安装与 IPA

在装有 **macOS、Xcode 26 或更高版本**的 Mac 上操作。先在 Xcode 登录 Apple 开发者账号。打开工程后，在 App target 的 **Signing & Capabilities** 选择 Team，设置该团队可用的 Bundle Identifier，启用自动签名。

```bash
npm ci
npm run sync
npm run ios:open
```

连接 iPhone 后，在 Xcode 选择该设备，点击 Run 可直接安装开发版并测试登录。

**在命令行导出内部测试 IPA**，先完成上述签名配置并在开发者账号中注册测试设备。下面的命令使用工程中配置的 Team 和 Bundle Identifier，以 Release 模式归档，再用已注册设备分发方式导出。

```bash
mkdir -p ios/output
xcodebuild -project ios/App/App.xcodeproj -scheme App -configuration Release \
  -destination 'generic/platform=iOS' -archivePath ios/output/App.xcarchive \
  -allowProvisioningUpdates archive

plutil -create xml1 ios/output/ExportOptions.plist
plutil -insert method -string release-testing ios/output/ExportOptions.plist
plutil -insert signingStyle -string automatic ios/output/ExportOptions.plist
xcodebuild -exportArchive -archivePath ios/output/App.xcarchive \
  -exportOptionsPlist ios/output/ExportOptions.plist -exportPath ios/output/internal \
  -allowProvisioningUpdates
ls -lh ios/output/internal/*.ipa
```

归档目录为 `ios/output/App.xcarchive`，**可分发的 IPA** 位于 `ios/output/internal/`。此签名的 IPA 可通过 Apple Configurator 安装到描述文件包含的 iPhone。若通过 TestFlight 分发，在 Xcode Organizer 选择归档，使用 **Distribute App → App Store Connect → Upload**，在 App Store Connect 添加测试人员，用户通过 TestFlight 安装。分发需要相应的 Apple Developer Program 团队权限。

## 功能范围

Git 只维护源码、工程配置、依赖锁文件、构建工具及原始资源。安装包、Xcode 归档、编译目录、签名文件及测试截图均保留在本地。

按账号权限展示工作台、两类问答和历史、机器人、用户、角色、页面路由、角色权限、个人信息、问答日志与审计日志。问答可查看命中片段。文档与知识库管理、文档预览上传、提示词管理、测评和问答日志导出 Word 保留在电脑端。手机的角色权限配置仍编辑整个平台的授权。
