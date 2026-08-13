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
Sources/<App>/
├── App/
├── Core/
│   ├── Networking/
│   └── Persistence/
└── Features/Home/
    ├── Models/
    ├── ViewModels/
    └── Views/
TREE
       ;;
    2) cat <<'TREE'
Sources/<App>/
├── App/
├── Core/
└── Features/Home/
    ├── Data/
    ├── Domain/
    └── Presentation/
TREE
       ;;
    3) cat <<'TREE'
Sources/<App>/
├── App/
├── Data/
│   ├── Networking/
│   └── Persistence/
├── Domain/
└── Presentation/
TREE
       ;;
    4) cat <<'TREE'
Sources/<App>/
├── App/
├── Models/
│   └── Services/
├── Views/
└── Controllers/
TREE
       ;;
    *) return 1 ;;
  esac
}

architecture_home_dir() {
  case "$1" in
    1) printf '%s\n' 'Features/Home/Views' ;;
    2) printf '%s\n' 'Features/Home/Presentation' ;;
    3) printf '%s\n' 'Presentation' ;;
    4) if [ "${2:-uikit}" = "swiftui" ]; then printf '%s\n' 'Views'; else printf '%s\n' 'Controllers'; fi ;;
    *) return 1 ;;
  esac
}

architecture_infrastructure_dir() {
  case "$1" in
    1|2) printf '%s\n' 'Core' ;;
    3) printf '%s\n' 'Data' ;;
    4) printf '%s\n' 'Models/Services' ;;
    *) return 1 ;;
  esac
}
