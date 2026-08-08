"""
背景画像の検索と選択を担当するモジュールです。

ゲーム進行や画面描画の処理から「どの画像ファイルを使用するか」という判断を分離し、
同じ `background_tag` に複数の画像を登録できるようにしています。

背景画像は、次の3つの方法で配置できます。

1. 従来どおり、タグと同じ名前の画像を1枚配置します。
   `assets/backgrounds/forest.jpg`
   `assets/backgrounds/forest.png`

2. タグ名のサブフォルダを作成し、その中に複数の画像を配置します（推奨）。
   `assets/backgrounds/forest/day.jpg`
   `assets/backgrounds/forest/night.jpg`

3. ルート直下に「タグ名__任意名」の形式で画像を配置します。
   `assets/backgrounds/forest__rain.jpg`

既存のタグへ画像を追加するだけであれば、
Pythonコードやタグの一覧を修正する必要はありません。

新しいタグそのものを追加する場合のみ、`game_prompts.py` の
`BACKGROUND_TAG_DESCRIPTIONS` にタグの説明を1行追加します。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import random


# JPGを先にすることで、同じタグのJPGとPNGが両方ある場合は
# 従来どおり容量を抑えやすいJPGを基準画像として採用する。
SUPPORTED_BACKGROUND_EXTENSIONS = (".jpg", ".jpeg", ".png")


class BackgroundImageCatalog:
    """
    タグに対応する画像を必要になった時点で検索し、表示順を決定する。

    全画像を起動時に読み込まず、ファイルパスだけをタグごとにキャッシュする。
    そのため、画像が100枚以上になっても大量の画像データを一度に
    メモリへ展開しない。
    """

    def __init__(
        self,
        *,
        background_dir: Path,
        valid_tags: Iterable[str],
        random_source: random.Random | None = None,
    ) -> None:
        self.background_dir = Path(background_dir)
        # 外部入力と比較しやすいよう、許可タグも小文字へ正規化して保持する。
        # noneは「画像を表示しない」という特別値なので、画像検索対象から外す。
        self.valid_tags = frozenset(
            normalized
            for tag in valid_tags
            if (normalized := self.normalize_tag(tag)) and normalized != "none"
        )
        self._random = random_source or random.Random()
        self._candidate_cache: dict[str, tuple[Path, ...]] = {}
        self._last_selected_by_tag: dict[str, Path] = {}

    @staticmethod
    def normalize_tag(tag: object) -> str:
        """LLM由来の値を、ファイル検索に使う小文字タグへそろえる。"""
        return str(tag).lower().strip()

    def is_supported_tag(self, tag: object) -> bool:
        """画像を持てる許可タグかを返す。noneや一覧外の値はFalseになる。"""
        return self.normalize_tag(tag) in self.valid_tags

    def candidates_for(self, tag: object) -> tuple[Path, ...]:
        """
        タグへ登録されている画像パスを返す。

        ディスク検索はタグごとの初回だけ行う。配布素材はアプリ実行中には
        変化しない前提なので、2回目以降はキャッシュを使って負荷を抑える。
        開発中に素材を追加した場合は、アプリを再起動すれば再検索される。
        """
        normalized_tag = self.normalize_tag(tag)
        if normalized_tag not in self.valid_tags:
            return ()

        if normalized_tag not in self._candidate_cache:
            self._candidate_cache[normalized_tag] = self._discover_candidates(
                normalized_tag
            )
        return self._candidate_cache[normalized_tag]

    def selection_order(self, tag: object) -> tuple[Path, ...]:
        """
        今回試す画像を、ランダムな優先順で返す。

        複数画像がある場合は直前に使った画像を最後へ回す。これにより、
        同じタグが続いても別画像を優先しつつ、ほかの画像が壊れている場合には
        最後の安全な候補として直前画像を再利用できる。
        """
        normalized_tag = self.normalize_tag(tag)
        candidates = self.candidates_for(normalized_tag)
        if len(candidates) <= 1:
            return candidates

        previous = self._last_selected_by_tag.get(normalized_tag)
        alternatives = [path for path in candidates if path != previous]
        self._random.shuffle(alternatives)

        if previous in candidates:
            alternatives.append(previous)
        return tuple(alternatives)

    def mark_selected(self, tag: object, image_path: Path) -> None:
        """正常に表示できた画像を記録し、次回の連続選択を避ける。"""
        normalized_tag = self.normalize_tag(tag)
        if image_path in self.candidates_for(normalized_tag):
            self._last_selected_by_tag[normalized_tag] = image_path

    def refresh(self, tag: object | None = None) -> None:
        """
        ファイル一覧のキャッシュを破棄する開発用の補助処理。

        通常プレイでは呼ぶ必要はないが、将来GUIから素材再読込を実装するときも
        背景選択の内部構造を変更せず利用できる。
        """
        if tag is None:
            self._candidate_cache.clear()
            return
        self._candidate_cache.pop(self.normalize_tag(tag), None)

    def _discover_candidates(self, tag: str) -> tuple[Path, ...]:
        """従来画像、ルート追加画像、タグ別フォルダの順に候補を収集する。"""
        candidates: list[Path] = []
        seen: set[Path] = set()

        def add_if_image(path: Path) -> None:
            """画像形式と重複を確認し、安全な候補だけを追加する。"""
            if (
                path.is_file()
                and path.suffix.lower() in SUPPORTED_BACKGROUND_EXTENSIONS
                and path not in seen
            ):
                seen.add(path)
                candidates.append(path)

        # 同名JPG/JPEG/PNGは「形式違いの代替」として扱い、優先順位が最も高い
        # 1枚だけを候補へ入れる。これで既存版のJPG優先動作を保つ。
        for extension in SUPPORTED_BACKGROUND_EXTENSIONS:
            legacy_path = self.background_dir / f"{tag}{extension}"
            if legacy_path.is_file():
                add_if_image(legacy_path)
                break

        # ルート直下へ置く場合は、別タグとの前方一致を避けるため
        # ``forest__rain.jpg`` のように区切りをアンダースコア2個へ統一する。
        root_variants = sorted(
            self.background_dir.glob(f"{tag}__*"),
            key=lambda path: path.name.casefold(),
        )
        for path in root_variants:
            add_if_image(path)

        # 大量追加時の推奨形式。フォルダ内のファイル名は自由に付けられるため、
        # day_01.jpgやnight_02.pngのように人が整理しやすい名前を使用できる。
        tag_directory = self.background_dir / tag
        if tag_directory.is_dir():
            folder_variants = sorted(
                tag_directory.iterdir(),
                key=lambda path: path.name.casefold(),
            )
            for path in folder_variants:
                add_if_image(path)

        return tuple(candidates)
