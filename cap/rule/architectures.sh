#!/usr/bin/env bash

architecture_name() {
  case "$1" in
    1) printf '%s\n' 'Feature-first MVVM' ;;
    2) printf '%s\n' 'Clean Architecture 3层' ;;
    3) printf '%s\n' 'Layer-first MVVM' ;;
    4) printf '%s\n' 'MVC' ;;
    *) return 1 ;;
  esac
}

architecture_tree() {
  case "$1" in
    1) cat <<'TREE'
app/src/main/kotlin/<package>/
├── app/
├── core/
│   ├── network/
│   └── storage/
└── features/home/
    ├── model/
    ├── state/
    └── ui/
TREE
       ;;
    2) cat <<'TREE'
app/src/main/kotlin/<package>/
├── app/
├── core/
└── features/home/
    ├── data/
    ├── domain/
    └── presentation/
TREE
       ;;
    3) cat <<'TREE'
app/src/main/kotlin/<package>/
├── app/
├── data/
│   ├── network/
│   └── storage/
├── domain/
└── presentation/
TREE
       ;;
    4) cat <<'TREE'
app/src/main/kotlin/<package>/
├── app/
├── model/
│   └── services/
├── view/
└── controller/
TREE
       ;;
    *) return 1 ;;
  esac
}

architecture_ui_dir() {
  case "$1" in
    1) printf '%s\n' 'features/home/ui' ;;
    2) printf '%s\n' 'features/home/presentation' ;;
    3) printf '%s\n' 'presentation' ;;
    4) printf '%s\n' 'view' ;;
    *) return 1 ;;
  esac
}

architecture_state_dir() {
  case "$1" in
    1) printf '%s\n' 'features/home/state' ;;
    2) printf '%s\n' 'features/home/presentation' ;;
    3) printf '%s\n' 'presentation' ;;
    4) printf '%s\n' 'model' ;;
    *) return 1 ;;
  esac
}

architecture_infrastructure_dir() {
  case "$1" in
    1) printf '%s\n' 'core' ;;
    2) printf '%s\n' 'features/home/data' ;;
    3) printf '%s\n' 'data' ;;
    4) printf '%s\n' 'model/services' ;;
    *) return 1 ;;
  esac
}
