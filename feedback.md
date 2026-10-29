wir haben ja den figma und nicht figma mode ich finde das hier irgendwie nicht so sauber und symstrisch ausgedürckt oder ist das leakge dass das figma ist weil das wäre der case hier für den canvas mode ehrlicherwe

def has_canvas_content(encoded: str, min_fraction: float) -> bool:
    """Reject neutral blank images and sparse central progress graphics."""
    with Image.open(BytesIO(base64.b64decode(encoded))) as source:
        image = source.convert("RGB")
        image.thumbnail((256, 256))
        pixels = list(image.getdata())
        if not pixels:
            return False
        common = image.getcolors(image.width * image.height) or []
        background = max(common, default=(0, (0, 0, 0)), key=lambda item: item[0])[1]
        changed = [(index % image.width, index // image.width)
                   for index, pixel in enumerate(pixels)
                   if max(abs(pixel[channel] - background[channel]) for channel in range(3)) > 25]
        if len(changed) < len(pixels) * min_fraction:
            return False
        spread = ImageStat.Stat(image).stddev
        if max(spread) < 2:
            return False
        if len(changed) < len(pixels) * 0.06:
            xs, ys = zip(*changed, strict=True)
            if (min(xs) > image.width * 0.2 and max(xs) < image.width * 0.8 and
                    min(ys) > image.height * 0.25 and max(ys) < image.height * 0.75):
                return False
        return True


z.B. hier ist mir das aufgefallen


    @hook(ObservationCapturedEvent)
    async def on_observation(
        self, event: ObservationCapturedEvent, browser: Inject[Browser]
    ) -> None:
        action = self.state.pending.pop(event.target_id, None)
        if action is None:
            return
        started_at = self.state.starts.pop(action.action_id, action.at)
        same_page = (
            action.before_url == event.url == action.after_url
            and action.before_document == event.document_id
            and action.target_id == event.target_id
        )
        if not same_page:
            return
        if (
            action.kind == "click"
            and not action.prepared_scroll
            and abs(event.scroll_y - action.before_scroll_y) >= 50
        ):
            delta = event.scroll_y - action.before_scroll_y
            await self.queue(
                browser,
                f"The page scrolled {abs(delta):.0f}px {'down' if delta > 0 else 'up'} after the click.",
                key="unexpected_scroll",
                cause_id=action.action_id,
                target_id=event.target_id,
                document_id=event.document_id,
            )
        if (
            action.expects_change
            and action.before_fingerprint == event.fingerprint
            and self.state.effect_at < started_at
            and event.readiness == "ready"
        ):
            await self.queue(
                browser,
                "The last action produced no observable page change; inspect before repeating it.",
                key="no_progress",
                cause_id=action.action_id,
                target_id=event.target_id,
                document_id=event.document_id,

ich weiß nciht was ich hier von dem string check auf .kind hier hlate gerne d aüfr auch ein StrEnum und mehr safety kind ist schon stabiler als die sigantur istabern eoch nciht genug
