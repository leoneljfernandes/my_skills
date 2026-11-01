// Adaptación del arnés, no del código de las skills: jsdom y undici (el `Request` de Node) no comparten
// clases, así que `request.formData()` de una action fallaría con el cuerpo que arma React Router.
// Sin esto, las actions de los tests darían resultados falsos.
import { URLSearchParams as NodeSearchParams } from "node:url";

const NodeRequest = globalThis.Request;

globalThis.Request = class extends NodeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    const body: unknown = init?.body;
    if (init && body && (body as object).constructor.name === "URLSearchParams") {
      init = { ...init, body: new NodeSearchParams(String(body)) };
    }
    super(input, init);
  }
};

NodeRequest.prototype.formData = async function (this: Request): Promise<FormData> {
  const form = new FormData();
  new NodeSearchParams(await this.text()).forEach((value, key) => form.append(key, value));
  return form;
};
