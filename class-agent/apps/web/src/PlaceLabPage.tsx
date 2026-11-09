import { PLACE_LAB_APP_URL } from "./placeLabRoute.js";

/* Place Lab as a page of the course site: the single-file build of GenerativeAgents/ (served from
   /placelab/) in a frame under the site's own header. The header stays, so Place Lab (pressed) or any
   other entry there is the way back; the browser's back button works too. */
export function PlaceLabPage() {
  return (
    <section aria-label="Place Lab" className="placelab-page">
      <iframe
        allow="camera"
        className="placelab-frame"
        src={PLACE_LAB_APP_URL}
        title="Place Lab simulation"
      />
    </section>
  );
}
