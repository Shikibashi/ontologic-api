"""Model compilation utilities for optimizing inference performance."""

import torch
from typing import Any, Optional
from app.core.logger import log

class ModelCompiler:
    """Handles safe model compilation with fallback mechanisms."""
    
    @staticmethod
    def try_better_transformer(model: Any, model_name: str = "model") -> Any:
        """
        Try to apply BetterTransformer optimization with silent fallback.
        
        Args:
            model: The model to optimize
            model_name: Name for logging purposes
            
        Returns:
            Optimized model or original model if optimization fails
        """
        try:
            # Try BetterTransformer first; fall back silently if unavailable
            from optimum.bettertransformer import BetterTransformer
            optimized_model = BetterTransformer.transform(model)
            log.info(f"BetterTransformer applied successfully to {model_name}")
            return optimized_model
        except ImportError:
            log.debug(f"BetterTransformer not available for {model_name} - proceeding without optimization")
            return model
        except Exception as e:
            log.warning(f"BetterTransformer failed for {model_name}: {e} - proceeding without optimization")
            return model
    
    @staticmethod  
    def try_torch_compile(model: Any, model_name: str = "model", mode: str = "reduce-overhead") -> Any:
        """
        Try to compile model with PyTorch 2.x compilation.
        
        Args:
            model: The model to compile
            model_name: Name for logging purposes  
            mode: Compilation mode ('reduce-overhead', 'default', 'max-autotune')
            
        Returns:
            Compiled model or original model if compilation fails
        """
        from app.config import get_settings
        settings = get_settings()
        
        if not settings.enable_compilation:
            log.info(f"Model compilation disabled via APP_ENABLE_COMPILATION=false for {model_name}")
            return model
            
        try:
            # Compile once — pays off during warmup, then reduces CPU overhead
            compiled_model = torch.compile(model, mode=mode, fullgraph=False)
            log.info(f"PyTorch compilation applied successfully to {model_name} (mode: {mode})")
            return compiled_model
        except Exception as e:
            log.warning(f"PyTorch compilation failed for {model_name}: {e} - proceeding without compilation")
            return model
    
    @staticmethod
    def optimize_model(model: Any, model_name: str = "model") -> Any:
        """
        Apply all available optimizations to a model.
        
        Args:
            model: The model to optimize
            model_name: Name for logging purposes
            
        Returns:
            Optimized model with BetterTransformer and/or compilation applied
        """
        # Apply BetterTransformer first
        model = ModelCompiler.try_better_transformer(model, model_name)
        
        # Then apply PyTorch compilation
        model = ModelCompiler.try_torch_compile(model, model_name)
        
        return model