from .open_ad_factory.nodes import OpenAdFactoryExtension


async def comfy_entrypoint() -> OpenAdFactoryExtension:
    return OpenAdFactoryExtension()
