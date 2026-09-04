# respect_gitignore가 실제로는 tracked-only 나열

`list_repository_files`는 `git ls-files`로 파일을 나열한다. 이는 gitignore를 존중하는 것이 아니라 git이 추적 중인 파일만 나열하는 것이므로, 아직 `git add` 하지 않은 새 파일이 그래프에서 통째로 빠진다. 실제 에이전트는 그 파일을 읽을 수 있으므로 관측 가능성 모델과 어긋난다.

옵션 이름을 동작에 맞추거나(`tracked_files_only`), gitignore를 직접 해석해 동작을 이름에 맞추는 선택이 필요하다. 어느 쪽이든 profile 파일의 키 이름이 바뀌므로 profile version을 올린다.
