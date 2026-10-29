"""Guardas de la identidad visual (v6.8).

Estas regresiones no truenan nada en el servidor, por eso no las atrapaba ningún test:
un logo de cliente escrito a mano, una fuente pedida a internet, un script que corre
antes de su librería. Se revisan sobre los archivos y el HTML servido.
"""
import json
import re
from pathlib import Path

from tests.conftest import login

STATIC = Path(__file__).resolve().parent.parent / 'backend' / 'static'
TEMPLATES = Path(__file__).resolve().parent.parent / 'backend' / 'templates'


def _archivos(base, *exts):
    for p in base.rglob('*'):
        if p.suffix in exts and 'vendor' not in p.parts:
            yield p


class TestMarcaDelProducto:

    def test_ningun_logo_de_cliente_en_el_producto(self):
        """El logo de Casa Leones salía en el modal de cobro de cualquier negocio."""
        culpables = [str(p) for p in _archivos(STATIC, '.js', '.css', '.json')
                     if 'logoCasaLeones' in p.read_text(encoding='utf-8')]
        culpables += [str(p) for p in _archivos(TEMPLATES, '.html')
                      if 'logoCasaLeones' in p.read_text(encoding='utf-8')]
        assert not culpables, culpables

    def test_manifest_es_del_producto(self):
        """La PWA instalada en la tablet de cualquier cliente decía "CasaLeones"."""
        m = json.loads((STATIC / 'manifest.json').read_text(encoding='utf-8'))
        assert m['name'] == 'KaiRest'
        assert 'Leones' not in json.dumps(m)
        for icono in m['icons']:
            assert (STATIC.parent / icono['src'].lstrip('/')).exists(), icono

    def test_iconos_livianos(self):
        """El favicon era un PNG de 1.1 MB y la mascota de la topbar 1.5 MB."""
        for nombre in ('icon-192.png', 'icon-512.png', 'icon-maskable-512.png', 'apple-touch-icon.png'):
            assert (STATIC / 'img' / nombre).stat().st_size < 60_000, nombre
        assert not (STATIC / 'img' / 'kainetResto.png').exists()


class TestTipografia:

    def test_sin_fuentes_externas(self):
        """El CSP es 'self': un @import a Google Fonts se bloquea y la fuente nunca carga."""
        externos = [str(p) for p in _archivos(STATIC, '.css')
                    if re.search(r'@import\s+url\([\'"]?https?://', p.read_text(encoding='utf-8'))]
        assert not externos, externos

    def test_inter_vendorizada(self):
        css = (STATIC / 'css' / 'tokens.css').read_text(encoding='utf-8')
        for archivo in re.findall(r"url\('\.\./(vendor/fonts/[^']+)'\)", css):
            assert (STATIC / archivo).exists(), archivo
        assert 'inter-latin-400.woff2' in css and 'inter-latin-600.woff2' in css


class TestScriptsEnOrden:

    def test_abrir_mesa_espera_a_bootstrap(self):
        """El script del modal "¿cuántas personas?" corría antes de bootstrap.bundle (al
        final de base.html): `bootstrap is not defined` y tocar una mesa no hacía nada."""
        html = (TEMPLATES / 'seleccionar_mesa.html').read_text(encoding='utf-8')
        i_modal = html.index('new bootstrap.Modal(modalEl)')
        i_listo = html.rfind("addEventListener('DOMContentLoaded'", 0, i_modal)
        assert i_listo != -1, 'new bootstrap.Modal debe correr dentro de DOMContentLoaded'

    def test_ordenes_activas_admin_carga_jquery_antes_de_meseros_js(
            self, client, db, superadmin_user):
        from backend.models.models import ConfiguracionSistema
        db.session.add(ConfiguracionSistema(clave='onboarding_completado', valor='true'))
        db.session.commit()
        login(client, superadmin_user.email, 'Test1234!')
        html = client.get('/meseros/').get_data(as_text=True)
        assert 'js/meseros.js' in html
        assert 'vendor/jquery.min.js' in html, 'meseros.js usa $ y truena sin jQuery'
        assert html.index('vendor/jquery.min.js') < html.index('js/meseros.js')
