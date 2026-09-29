# 源码布局

当前 Python 和 Studio 源码都在 `src/`：

```text
src/statebus/   Runtime、contracts、control、state、memory、benchmark、Studio backend
src/studio-ui/  React/TypeScript Studio frontend
```

Python import 使用 `src` package root；Studio 的构建产物由 backend 从 `src/studio-ui/dist` 提供。任务输入和 validator 位于 `tasks/`，不是源码目录。
