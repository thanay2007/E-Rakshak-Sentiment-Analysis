# Fictional directory demo

Three fictional profiles with locally saved PNG portraits for testing directory
cards, image uploads, and manual record selection.

- `profiles.json`: names, roles, bios, and image references.
- `images/milo-muffin.png`: Milo Muffin, Chief Snack Officer.
- `images/tessa-teacup.png`: Tessa Teacup, Tea Quality Inspector.
- `images/otto-noodle.png`: Otto Noodle, Pasta Researcher.
- `sources.json`: image provenance and exact generation prompts.

All pictures were created using the built-in image_gen tool. They are synthetic
cartoon portraits, not photographs of real people or downloaded mugshots.
There are no external image-source URLs.

Image paths are relative to this folder. Select one of the PNGs to test an image
upload control, or load `profiles.json` for a directory display fixture. Display
the supplied `image_alt` and an “AI-generated / fictional” label with each image.

`case_histories.json` contains invented, humorous case histories. Every profile
and every case returned by the API carries the label **Synthetic demo data — not
a real criminal record**.

The backend now stores these records and their PNG bytes in the separate
`demodirectoryprofile` table. Migration `0009_demo_directory` creates the table;
backend startup seeds missing demo profiles without overwriting existing rows.
They are not registered with the face gallery or connected to identity matching.

Restart the backend normally, or seed without starting the server:

```bash
python -m app.data.directory_seed
```

Authenticated endpoints (use the same Bearer token as the rest of the API):

- `GET /api/demo-directory`: list all three profiles.
- `GET /api/demo-directory?q=Milo`: manually search by name or record ID.
- `GET /api/demo-directory/demo-milo-muffin`: retrieve a chosen record.
- `GET /api/demo-directory/demo-milo-muffin/image`: retrieve its stored PNG.

For a backend demonstration, open `http://localhost:8000/docs`, use Authorize
with your existing access token, and expand the `demo-directory` endpoints.
Select a profile by name or ID. Include the Authorization header when fetching
its `image_url`; a plain browser `<img>` does not send a Bearer header, so a
client should fetch the image as a blob using its normal authenticated API
helper.

The frontend Demo Directory page was removed. The fixtures and backend manual
lookup endpoints remain available; use the authenticated API documentation to
inspect them.
